"""
Simple AI service mock for Lab 05.

This service exposes two endpoints:

* `GET /health` – returns status, service name and version.
* `POST /predict` – returns a dummy list of detected objects and confidences.

You can replace this file with your actual inference code (e.g. YOLOv8 model).
"""

from fastapi import FastAPI, HTTPException
from pydantic import BaseModel
from typing import List, Optional
import httpx
from ultralytics import YOLO
import urllib.request
import os

# Load YOLOv8 model (downloads 'yolov8n.pt' on first run)
model = YOLO('yolov8n.pt')


SERVICE_NAME = "ai-service"
SERVICE_VERSION = "0.5.0"

app = FastAPI(
    title="FIT4110 Lab 05 - AI Service",
    version=SERVICE_VERSION,
    description="Mock AI service used in Docker Compose stack.",
)


class PredictRequest(BaseModel):
    imageRef: Optional[str] = None

class Prediction(BaseModel):
    objects: List[str]
    confidence: List[float]


@app.get("/health")
def health() -> dict:
    return {"status": "ok", "service": SERVICE_NAME, "version": SERVICE_VERSION}


@app.post("/predict", response_model=Prediction)
async def predict(payload: PredictRequest) -> Prediction:
    # Use a default sample image for S3/mock cases
    image_url = "https://ultralytics.com/images/bus.jpg"
    
    # Run YOLOv8 inference
    try:
        results = model(image_url)
        objects = []
        confidences = []
        
        for result in results:
            boxes = result.boxes
            for box in boxes:
                # get class label and confidence
                class_id = int(box.cls[0])
                conf = float(box.conf[0])
                label = model.names[class_id]
                
                objects.append(label.upper())
                confidences.append(conf)
                
        # If nothing is detected, fallback to default
        if not objects:
            objects = ["PERSON"]
            confidences = [0.99]
            
        return Prediction(objects=objects, confidence=confidences)
    except Exception as e:
        print(f"YOLO Inference Error: {e}")
        raise HTTPException(status_code=500, detail="Inference failed")


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=9000)