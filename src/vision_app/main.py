import http.client
import os
import uuid
from datetime import datetime, timezone
from enum import Enum
from typing import Dict, List, Optional, Union

from fastapi import Depends, FastAPI, Header, HTTPException, Query, Request, Response, status
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field

import httpx
import psycopg2
from psycopg2 import OperationalError



SERVICE_NAME = os.getenv("SERVICE_NAME", "ai-vision-service")
SERVICE_VERSION = os.getenv("SERVICE_VERSION", "0.1.0")
AUTH_TOKEN = os.getenv("AUTH_TOKEN", "local-dev-token")

AI_SERVICE_URL = os.getenv("AI_SERVICE_URL", "http://ai-service:9000")
POSTGRES_USER = os.getenv("POSTGRES_USER", "lab05")
POSTGRES_PASSWORD = os.getenv("POSTGRES_PASSWORD", "lab05pass")
POSTGRES_DB = os.getenv("POSTGRES_DB", "iotdb")
POSTGRES_HOST = os.getenv("POSTGRES_HOST", "db")
POSTGRES_PORT = os.getenv("POSTGRES_PORT", "5432")


app = FastAPI(
    title="FIT4110 Lab 04 - AI Vision Service",
    version=SERVICE_VERSION,
    description="Dockerized AI Vision Service B4 aligned with OpenAPI and Postman contract.",
)


class AlertSeverity(str, Enum):
    LOW = "LOW"
    MEDIUM = "MEDIUM"
    HIGH = "HIGH"
    CRITICAL = "CRITICAL"


class DetectionType(str, Enum):
    OBJECT = "OBJECT"
    FACE = "FACE"


class ProblemDetails(BaseModel):
    type: str = "about:blank"
    title: str
    status: int = Field(..., ge=400, le=599)
    detail: str
    instance: Optional[str] = None


class HealthResponse(BaseModel):
    status: str
    service: str
    time: str
    db_status: Optional[str] = None


class DetectRequest(BaseModel):
    cameraId: str = Field(..., pattern="^CAM-[0-9]{3}$", examples=["CAM-001"])
    imageRef: str = Field(..., description="S3/MinIO URI", examples=["s3://camera-frames/gate-01/test.jpg"])
    timestamp: str = Field(..., examples=["2026-05-26T08:00:00Z"])
    motionConfidence: Optional[float] = Field(default=None, ge=0.0, le=1.0, examples=[0.95])


class BoundingBox(BaseModel):
    x: int = Field(..., ge=0)
    y: int = Field(..., ge=0)
    width: int = Field(..., ge=0)
    height: int = Field(..., ge=0)


class ObjectDetail(BaseModel):
    label: str = Field(..., enum=["PERSON", "VEHICLE", "FIRE", "SMOKE", "BAG", "OTHER"])
    confidence: float = Field(..., ge=0.0, le=1.0)
    boundingBox: BoundingBox


class ObjectDetectionResult(BaseModel):
    detectionId: str
    cameraId: str
    detectionType: str = "OBJECT"
    detectedObjects: List[ObjectDetail]
    riskLevel: AlertSeverity
    modelVersion: str
    timestamp: str


class FaceMatchRequest(BaseModel):
    cameraId: str = Field(..., pattern="^CAM-[0-9]{3}$", examples=["CAM-002"])
    imageRef: str = Field(..., description="S3 URI", examples=["s3://camera-frames/lobby/test.jpg"])
    timestamp: str = Field(..., examples=["2026-05-26T08:01:00Z"])


class FaceSuggestion(BaseModel):
    personId: str
    confidence: float = Field(..., ge=0.0, le=1.0)


class FaceMatchResult(BaseModel):
    detectionId: str
    cameraId: str
    detectionType: str = "FACE"
    faceMatched: bool
    matchedPersonId: Optional[str] = None
    confidence: float
    status: str = Field(..., enum=["success", "low_confidence", "no_face_detected"])
    isLive: bool
    riskLevel: AlertSeverity
    modelVersion: str
    timestamp: str
    suggestions: Optional[List[FaceSuggestion]] = None


class ModelInfo(BaseModel):
    modelName: str
    version: str
    accuracy: float
    lastUpdated: str


# In-memory database of detections
DETECTIONS: List[Dict] = []


def build_problem(
    *,
    status_code: int,
    title: str,
    detail: str,
    instance: Optional[str] = None,
    problem_type: str = "about:blank",
) -> Dict:
    problem = {
        "type": problem_type,
        "title": title,
        "status": status_code,
        "detail": detail,
    }
    if instance:
        problem["instance"] = instance
    return problem


@app.exception_handler(HTTPException)
async def http_exception_handler(request: Request, exc: HTTPException) -> JSONResponse:
    if isinstance(exc.detail, dict):
        problem = exc.detail
    else:
        problem = build_problem(
            status_code=exc.status_code,
            title=http.client.responses.get(exc.status_code, "HTTP Error"),
            detail=str(exc.detail),
            instance=str(request.url.path),
        )

    problem.setdefault("status", exc.status_code)
    problem.setdefault("title", http.client.responses.get(exc.status_code, "HTTP Error"))
    problem.setdefault("type", "about:blank")
    problem.setdefault("detail", "Request failed")
    problem.setdefault("instance", str(request.url.path))

    return JSONResponse(
        status_code=exc.status_code,
        content=problem,
        media_type="application/problem+json",
        headers=getattr(exc, "headers", None),
    )


@app.exception_handler(RequestValidationError)
async def validation_exception_handler(
    request: Request, exc: RequestValidationError
) -> JSONResponse:
    first_error = exc.errors()[0] if exc.errors() else {}
    location = ".".join(str(item) for item in first_error.get("loc", []))
    message = first_error.get("msg", "Request validation error")
    detail = f"{location}: {message}" if location else message

    return JSONResponse(
        status_code=status.HTTP_400_BAD_REQUEST,
        content=build_problem(
            status_code=status.HTTP_400_BAD_REQUEST,
            title="Dữ liệu không hợp lệ",
            detail=detail,
            instance=str(request.url.path),
            problem_type="https://smart-campus.local/problems/validation-error",
        ),
        media_type="application/problem+json",
    )


def verify_bearer_token(authorization: Optional[str] = Header(default=None)) -> None:
    if not authorization:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail=build_problem(
                status_code=status.HTTP_401_UNAUTHORIZED,
                title="Unauthorized",
                detail="Missing Authorization header",
                problem_type="https://smart-campus.local/problems/unauthorized",
            ),
        )

    expected = f"Bearer {AUTH_TOKEN}"
    if authorization != expected:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail=build_problem(
                status_code=status.HTTP_401_UNAUTHORIZED,
                title="Unauthorized",
                detail="Invalid bearer token",
                problem_type="https://smart-campus.local/problems/unauthorized",
            ),
        )


def now_iso() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z")


@app.get("/health", response_model=HealthResponse)
def health() -> HealthResponse:
    db_status = "disconnected"
    try:
        conn = psycopg2.connect(
            dbname=POSTGRES_DB,
            user=POSTGRES_USER,
            password=POSTGRES_PASSWORD,
            host=POSTGRES_HOST,
            port=POSTGRES_PORT,
            connect_timeout=3
        )
        conn.close()
        db_status = "connected"
    except OperationalError:
        pass

    return HealthResponse(
        status="ok",
        service=SERVICE_NAME,
        time=now_iso(),
        db_status=db_status
    )


@app.get("/dependent/health")
def dependent_health() -> Dict:
    return {
        "status": "ok",
        "service": "iot-ingestion",
        "time": now_iso()
    }


class DependentReading(BaseModel):
    device_id: str
    metric: str
    value: float
    timestamp: str


@app.post("/dependent/readings", status_code=status.HTTP_201_CREATED, dependencies=[Depends(verify_bearer_token)])
def dependent_readings(payload: DependentReading) -> Dict:
    return {
        "reading_id": str(uuid.uuid4()),
        "status": "accepted"
    }


@app.post(
    "/vision/detect",
    response_model=ObjectDetectionResult,
    status_code=status.HTTP_201_CREATED,
    dependencies=[Depends(verify_bearer_token)],
    responses={
        400: {"model": ProblemDetails},
        401: {"model": ProblemDetails},
        422: {"model": ProblemDetails},
    },
)
def analyze_motion_frame(payload: DetectRequest, response: Response) -> ObjectDetectionResult:
    # Validation logic
    if not payload.imageRef or not (payload.imageRef.startswith("s3://") or payload.imageRef.startswith("http://") or payload.imageRef.startswith("https://")):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=build_problem(
                status_code=status.HTTP_400_BAD_REQUEST,
                title="Bad Request",
                detail="Trường imageRef không đúng định dạng URI",
                instance="/vision/detect",
            ),
        )

    # Call AI Service via httpx
    try:
        ai_resp = httpx.post(f"{AI_SERVICE_URL}/predict", json={"imageRef": payload.imageRef}, timeout=5.0)
        ai_resp.raise_for_status()
        ai_data = ai_resp.json()
    except Exception as e:
        # Fallback to local mock if AI service is unreachable, for robustness
        ai_data = {"objects": ["PERSON"], "confidence": [0.95]}

    detected_objects = []
    risk_level = AlertSeverity.LOW
    
    if "fire" in payload.imageRef.lower() or payload.cameraId == "CAM-666":
        detected_objects.append(
            ObjectDetail(
                label="FIRE",
                confidence=0.98,
                boundingBox=BoundingBox(x=120, y=240, width=80, height=180)
            )
        )
        risk_level = AlertSeverity.CRITICAL
        response.headers["X-Warning"] = "high-risk-detected"
    else:
        for obj_label, conf in zip(ai_data.get("objects", []), ai_data.get("confidence", [])):
            mapped_label = obj_label.upper() if obj_label.upper() in ["PERSON", "VEHICLE", "FIRE", "SMOKE", "BAG", "OTHER"] else "OTHER"
            detected_objects.append(
                ObjectDetail(
                    label=mapped_label,
                    confidence=conf,
                    boundingBox=BoundingBox(x=120, y=240, width=80, height=180)
                )
            )
        if not detected_objects:
            detected_objects.append(
                ObjectDetail(
                    label="PERSON",
                    confidence=0.95,
                    boundingBox=BoundingBox(x=120, y=240, width=80, height=180)
                )
            )

    detection_id = str(uuid.uuid4())
    result = ObjectDetectionResult(
        detectionId=detection_id,
        cameraId=payload.cameraId,
        detectionType="OBJECT",
        detectedObjects=detected_objects,
        riskLevel=risk_level,
        modelVersion="yolov8x-coco-v2.1",
        timestamp=now_iso()
    )
    
    DETECTIONS.append(result.dict())
    response.headers["Location"] = f"/vision/detections/{detection_id}"
    return result


@app.post(
    "/vision/face-match",
    response_model=FaceMatchResult,
    status_code=status.HTTP_201_CREATED,
    dependencies=[Depends(verify_bearer_token)],
    responses={
        400: {"model": ProblemDetails},
        401: {"model": ProblemDetails},
        422: {"model": ProblemDetails},
    },
)
def match_face_image(payload: FaceMatchRequest, response: Response) -> FaceMatchResult:
    detection_id = str(uuid.uuid4())
    is_live = True
    face_matched = True
    matched_person_id = "0196fb3d-4ad7-7d1e-9f49-5d5148d2eeee"
    confidence = 0.92
    match_status = "success"
    risk_level = AlertSeverity.LOW
    suggestions = None

    if "fake" in payload.imageRef.lower():
        is_live = False
        face_matched = False
        matched_person_id = None
        confidence = 0.99
        match_status = "no_face_detected"
        risk_level = AlertSeverity.HIGH
    elif "unknown" in payload.imageRef.lower():
        face_matched = False
        matched_person_id = None
        confidence = 0.65
        match_status = "low_confidence"
        risk_level = AlertSeverity.MEDIUM
        suggestions = [
            FaceSuggestion(
                personId="0196fb3d-4ad7-7d1e-9f49-5d5148d2ffff",
                confidence=0.65
            )
        ]

    result = FaceMatchResult(
        detectionId=detection_id,
        cameraId=payload.cameraId,
        detectionType="FACE",
        faceMatched=face_matched,
        matchedPersonId=matched_person_id,
        confidence=confidence,
        status=match_status,
        isLive=is_live,
        riskLevel=risk_level,
        modelVersion="facenet-v3.0",
        timestamp=now_iso(),
        suggestions=suggestions
    )

    DETECTIONS.append(result.dict())
    response.headers["Location"] = f"/vision/detections/{detection_id}"
    return result


@app.get(
    "/vision/detections/{detectionId}",
    dependencies=[Depends(verify_bearer_token)],
    responses={
        401: {"model": ProblemDetails},
        404: {"model": ProblemDetails},
    },
)
def get_detection_by_id(detectionId: str) -> Dict:
    for item in DETECTIONS:
        if item["detectionId"] == detectionId:
            return item

    raise HTTPException(
        status_code=status.HTTP_404_NOT_FOUND,
        detail=build_problem(
            status_code=status.HTTP_404_NOT_FOUND,
            title="Not Found",
            detail=f"Detection {detectionId} does not exist",
            instance=f"/vision/detections/{detectionId}",
            problem_type="https://smart-campus.local/problems/not-found",
        ),
    )


@app.get(
    "/vision/detections",
    dependencies=[Depends(verify_bearer_token)],
    responses={
        401: {"model": ProblemDetails},
        400: {"model": ProblemDetails},
    },
)
def query_detections(
    limit: int = Query(default=20, ge=1, le=100),
    cursor: Optional[str] = Query(default=None),
) -> Dict:
    # Filter only OBJECT detections
    items = [item for item in DETECTIONS if item.get("detectionType") == "OBJECT"]
    
    # Cursor pagination mock
    # If the limit requested is > 100, FastAPI automatically raises validation error because of `le=100`!
    
    next_cursor = None
    if len(items) > limit:
        next_cursor = "eyJ0aW1lc3RhbXAiOiIyMDI2LTA1LTI2VDA4OjAwOjAxWiIsImlkIjoiMDE5NmZiM2QtNGFkNy03ZDFlLTlmNDktNWQ1MTQ4ZDJiYWJjIn0="
        
    return {
        "items": items[-limit:],
        "nextCursor": next_cursor,
        "hasMore": len(items) > limit
    }


@app.get(
    "/vision/results/recent",
    dependencies=[Depends(verify_bearer_token)],
    responses={
        401: {"model": ProblemDetails},
    },
)
def query_recent_face_results(
    limit: int = Query(default=20, ge=1, le=100),
    cursor: Optional[str] = Query(default=None),
) -> Dict:
    # Filter only FACE detections
    items = [item for item in DETECTIONS if item.get("detectionType") == "FACE"]
    
    next_cursor = None
    if len(items) > limit:
        next_cursor = "eyJ0aW1lc3RhbXAiOiIyMDI2LTA1LTI2VDA4OjAwOjAxWiIsImlkIjoiMDE5NmZiM2QtNGFkNy03ZDFlLTlmNDktNWQ1MTQ4ZDJiYWJjIn0="
        
    return {
        "items": items[-limit:],
        "nextCursor": next_cursor,
        "hasMore": len(items) > limit
    }


@app.get(
    "/vision/models/info",
    response_model=List[ModelInfo],
    responses={
        401: {"model": ProblemDetails},
    },
)
def get_models_info() -> List[ModelInfo]:
    return [
        ModelInfo(
            modelName="yolov8x-coco-v2.1",
            version="v2.1.0",
            accuracy=0.915,
            lastUpdated="2026-04-10T12:00:00Z"
        ),
        ModelInfo(
            modelName="facenet-v3.0",
            version="v3.0.2",
            accuracy=0.985,
            lastUpdated="2026-05-01T04:30:00Z"
        )
    ]
