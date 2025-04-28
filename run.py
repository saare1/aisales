#!/usr/bin/env python
import uvicorn
from app.core.config import settings

if __name__ == "__main__":
    print(f"Starting AI Sales Closer Agent on port {settings.API_PORT}")
    uvicorn.run(
        "app.main:app",
        host="0.0.0.0",
        port=settings.API_PORT,
        reload=settings.DEBUG,
    ) 