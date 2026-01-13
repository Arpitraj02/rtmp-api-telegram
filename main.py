import os
import json
import subprocess
import time
import threading
from pathlib import Path
from typing import Optional, List, Dict, Any
from datetime import datetime

from fastapi import FastAPI, File, UploadFile, HTTPException, BackgroundTasks
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
import uvicorn

# ============================================================================
# CONFIGURATION & CONSTANTS
# ============================================================================

VIDEOS_DIR = Path("videos")
SETTINGS_FILE = Path("settings.json")
QUEUE_FILE = Path("queue.json")

VIDEOS_DIR.mkdir(exist_ok=True)

DEFAULT_SETTINGS = {
    "rtmp_url": "rtmp://example.com/live",
    "stream_key": "your_stream_key",
    "resolution": "1920x1080",
    "bitrate": 2500,
    "fps": 30
}

# ============================================================================
# PYDANTIC MODELS
# ============================================================================

class StreamSettings(BaseModel):
    rtmp_url: str
    stream_key: str
    resolution: str = "1920x1080"
    bitrate: int = 2500
    fps: int = 30

class QueueItem(BaseModel):
    video_id: str

class VideoMetadata(BaseModel):
    id: str
    name: str
    size: int
    created_at: str

class StreamStatus(BaseModel):
    isActive: bool
    currentVideoId: Optional[str]
    uptime: int
    status: str
    queue: List[str]
    viewerCount: int

# ============================================================================
# GLOBAL STATE MANAGEMENT
# ============================================================================

class StreamManager:
    def __init__(self):
        self.process: Optional[subprocess.Popen] = None
        self.is_active = False
        self.current_video_id: Optional[str] = None
        self.start_time: Optional[float] = None
        self.queue: List[str] = []
        self.lock = threading.Lock()
        self.stream_thread: Optional[threading.Thread] = None
        self.should_stop = False
        
        # Load queue from disk
        self._load_queue()
    
    def _load_queue(self):
        """Load queue from JSON file"""
        if QUEUE_FILE.exists():
            try:
                with open(QUEUE_FILE, 'r') as f:
                    self.queue = json.load(f)
            except Exception as e:
                print(f"Error loading queue: {e}")
                self.queue = []
    
    def _save_queue(self):
        """Save queue to JSON file"""
        try:
            with open(QUEUE_FILE, 'w') as f:
                json.dump(self.queue, f, indent=2)
        except Exception as e:
            print(f"Error saving queue: {e}")
    
    def add_to_queue(self, video_id: str):
        """Add video to queue"""
        with self.lock:
            if video_id not in self.queue:
                self.queue.append(video_id)
                self._save_queue()
    
    def remove_from_queue(self, video_id: str):
        """Remove video from queue"""
        with self.lock:
            if video_id in self.queue:
                self.queue.remove(video_id)
                self._save_queue()
    
    def get_next_video(self) -> Optional[str]:
        """Get next video from queue"""
        with self.lock:
            if self.queue:
                video_id = self.queue.pop(0)
                self._save_queue()
                return video_id
            return None
    
    def start_stream(self, settings: Dict[str, Any]):
        """Start streaming with queue management"""
        if self.is_active:
            raise Exception("Stream is already active")
        
        self.should_stop = False
        self.stream_thread = threading.Thread(target=self._stream_loop, args=(settings,))
        self.stream_thread.daemon = True
        self.stream_thread.start()
    
    def _stream_loop(self, settings: Dict[str, Any]):
        """Main streaming loop that processes queue"""
        while not self.should_stop:
            video_id = self.get_next_video()
            
            if not video_id:
                print("Queue is empty. Stopping stream.")
                break
            
            video_path = VIDEOS_DIR / video_id
            
            if not video_path.exists():
                print(f"Video {video_id} not found. Skipping.")
                continue
            
            try:
                self._stream_video(video_path, settings)
            except Exception as e:
                print(f"Error streaming {video_id}: {e}")
                time.sleep(1)  # Brief pause before next video
        
        # Clean up when loop ends
        with self.lock:
            self.is_active = False
            self.current_video_id = None
            self.start_time = None
    
    def _stream_video(self, video_path: Path, settings: Dict[str, Any]):
        """Stream a single video using FFmpeg"""
        rtmp_url = settings['rtmp_url']
        stream_key = settings['stream_key']
        bitrate = settings['bitrate']
        resolution = settings['resolution']
        fps = settings['fps']
        
        # Construct FFmpeg command
        cmd = [
            'ffmpeg',
            '-re',  # Real-time mode
            '-i', str(video_path),
            '-c:v', 'libx264',
            '-preset', 'veryfast',
            '-b:v', f'{bitrate}k',
            '-maxrate', f'{bitrate}k',
            '-bufsize', f'{bitrate * 2}k',
            '-pix_fmt', 'yuv420p',
            '-g', '50',
            '-s', resolution,
            '-r', str(fps),
            '-c:a', 'aac',
            '-b:a', '128k',
            '-ar', '44100',
            '-f', 'flv',
            f'{rtmp_url}/{stream_key}'
        ]
        
        print(f"Starting stream: {video_path.name}")
        
        with self.lock:
            self.current_video_id = video_path.name
            self.is_active = True
            if self.start_time is None:
                self.start_time = time.time()
        
        try:
            self.process = subprocess.Popen(
                cmd,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                universal_newlines=True
            )
            
            # Wait for process to complete
            self.process.wait()
            
            if self.process.returncode != 0 and not self.should_stop:
                stderr = self.process.stderr.read() if self.process.stderr else ""
                print(f"FFmpeg error: {stderr}")
        
        except Exception as e:
            print(f"Exception during streaming: {e}")
        
        finally:
            self.process = None
            with self.lock:
                self.current_video_id = None
    
    def stop_stream(self):
        """Stop the stream gracefully"""
        self.should_stop = True
        
        if self.process:
            try:
                self.process.terminate()
                self.process.wait(timeout=5)
            except subprocess.TimeoutExpired:
                self.process.kill()
            except Exception as e:
                print(f"Error stopping process: {e}")
            finally:
                self.process = None
        
        with self.lock:
            self.is_active = False
            self.current_video_id = None
            self.start_time = None
    
    def skip_current(self):
        """Skip current video and move to next"""
        if self.process:
            try:
                self.process.terminate()
                self.process.wait(timeout=5)
            except subprocess.TimeoutExpired:
                self.process.kill()
            except Exception as e:
                print(f"Error skipping video: {e}")
    
    def get_status(self) -> Dict[str, Any]:
        """Get current stream status"""
        with self.lock:
            uptime = int(time.time() - self.start_time) if self.start_time else 0
            status = "streaming" if self.is_active else "idle"
            
            return {
                "isActive": self.is_active,
                "currentVideoId": self.current_video_id,
                "uptime": uptime,
                "status": status,
                "queue": self.queue.copy(),
                "viewerCount": 0  # Placeholder - Telegram doesn't provide this
            }

# ============================================================================
# UTILITY FUNCTIONS
# ============================================================================

def load_settings() -> Dict[str, Any]:
    """Load RTMP settings from JSON file"""
    if SETTINGS_FILE.exists():
        try:
            with open(SETTINGS_FILE, 'r') as f:
                return json.load(f)
        except Exception as e:
            print(f"Error loading settings: {e}")
    
    # Return and save default settings
    save_settings(DEFAULT_SETTINGS)
    return DEFAULT_SETTINGS

def save_settings(settings: Dict[str, Any]):
    """Save RTMP settings to JSON file"""
    try:
        with open(SETTINGS_FILE, 'w') as f:
            json.dump(settings, f, indent=2)
    except Exception as e:
        print(f"Error saving settings: {e}")
        raise HTTPException(status_code=500, detail=f"Failed to save settings: {e}")

def get_video_metadata(video_path: Path) -> VideoMetadata:
    """Get metadata for a video file"""
    stat = video_path.stat()
    return VideoMetadata(
        id=video_path.name,
        name=video_path.name,
        size=stat.st_size,
        created_at=datetime.fromtimestamp(stat.st_ctime).isoformat()
    )

# ============================================================================
# FASTAPI APPLICATION
# ============================================================================

app = FastAPI(
    title="Live Stream Control Center API",
    description="Backend API for managing RTMP streams to Telegram",
    version="1.0.0"
)

# Enable CORS
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Initialize stream manager
stream_manager = StreamManager()

# ============================================================================
# API ENDPOINTS
# ============================================================================

@app.get("/")
async def root():
    """Health check endpoint"""
    return {
        "message": "Live Stream Control Center API",
        "status": "online",
        "version": "1.0.0"
    }

@app.get("/status", response_model=StreamStatus)
async def get_status():
    """Get current stream status"""
    return stream_manager.get_status()

@app.get("/videos", response_model=List[VideoMetadata])
async def list_videos():
    """List all videos in the videos directory"""
    try:
        videos = []
        for video_file in VIDEOS_DIR.glob("*"):
            if video_file.is_file() and video_file.suffix.lower() in ['.mp4', '.mkv', '.avi', '.mov']:
                videos.append(get_video_metadata(video_file))
        
        # Sort by creation time, newest first
        videos.sort(key=lambda x: x.created_at, reverse=True)
        return videos
    
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Error listing videos: {e}")

@app.post("/upload")
async def upload_video(file: UploadFile = File(...)):
    """Upload a video file"""
    # Validate file extension
    if not file.filename:
        raise HTTPException(status_code=400, detail="No filename provided")
    
    file_ext = Path(file.filename).suffix.lower()
    if file_ext not in ['.mp4', '.mkv', '.avi', '.mov']:
        raise HTTPException(status_code=400, detail="Invalid file type. Only MP4, MKV, AVI, and MOV are supported.")
    
    # Generate unique filename
    timestamp = int(time.time())
    safe_filename = f"{timestamp}_{file.filename}"
    file_path = VIDEOS_DIR / safe_filename
    
    try:
        # Save file in chunks
        with open(file_path, 'wb') as f:
            while chunk := await file.read(1024 * 1024):  # 1MB chunks
                f.write(chunk)
        
        return {
            "message": "File uploaded successfully",
            "video": get_video_metadata(file_path)
        }
    
    except Exception as e:
        # Clean up partial file if error occurs
        if file_path.exists():
            file_path.unlink()
        raise HTTPException(status_code=500, detail=f"Error uploading file: {e}")

@app.delete("/video/{video_id}")
async def delete_video(video_id: str):
    """Delete a specific video file"""
    video_path = VIDEOS_DIR / video_id
    
    if not video_path.exists():
        raise HTTPException(status_code=404, detail="Video not found")
    
    # Check if video is currently streaming
    status = stream_manager.get_status()
    if status['currentVideoId'] == video_id:
        raise HTTPException(status_code=400, detail="Cannot delete video that is currently streaming")
    
    # Remove from queue if present
    stream_manager.remove_from_queue(video_id)
    
    try:
        video_path.unlink()
        return {"message": "Video deleted successfully", "video_id": video_id}
    
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Error deleting video: {e}")

@app.get("/settings")
async def get_settings():
    """Get current RTMP settings"""
    return load_settings()

@app.post("/settings")
async def update_settings(settings: StreamSettings):
    """Update RTMP settings"""
    settings_dict = settings.dict()
    save_settings(settings_dict)
    return {"message": "Settings updated successfully", "settings": settings_dict}

@app.post("/stream/start")
async def start_stream(background_tasks: BackgroundTasks):
    """Start the stream with queue"""
    if stream_manager.is_active:
        raise HTTPException(status_code=400, detail="Stream is already active")
    
    if not stream_manager.queue:
        raise HTTPException(status_code=400, detail="Queue is empty. Add videos to queue first.")
    
    settings = load_settings()
    
    try:
        stream_manager.start_stream(settings)
        return {"message": "Stream started successfully"}
    
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Error starting stream: {e}")

@app.post("/stream/stop")
async def stop_stream():
    """Stop the active stream"""
    if not stream_manager.is_active:
        raise HTTPException(status_code=400, detail="No active stream to stop")
    
    try:
        stream_manager.stop_stream()
        return {"message": "Stream stopped successfully"}
    
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Error stopping stream: {e}")

@app.post("/stream/skip")
async def skip_video():
    """Skip current video and play next in queue"""
    if not stream_manager.is_active:
        raise HTTPException(status_code=400, detail="No active stream")
    
    try:
        stream_manager.skip_current()
        return {"message": "Skipped to next video"}
    
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Error skipping video: {e}")

@app.post("/queue/add")
async def add_to_queue(item: QueueItem):
    """Add a video to the play queue"""
    video_path = VIDEOS_DIR / item.video_id
    
    if not video_path.exists():
        raise HTTPException(status_code=404, detail="Video not found")
    
    stream_manager.add_to_queue(item.video_id)
    return {"message": "Video added to queue", "queue": stream_manager.queue}

@app.delete("/queue/remove/{video_id}")
async def remove_from_queue(video_id: str):
    """Remove a video from the queue"""
    stream_manager.remove_from_queue(video_id)
    return {"message": "Video removed from queue", "queue": stream_manager.queue}

@app.get("/queue")
async def get_queue():
    """Get current queue"""
    return {"queue": stream_manager.queue}

# ============================================================================
# APPLICATION ENTRY POINT
# ============================================================================

if __name__ == "__main__":
    port = int(os.environ.get("PORT", 8000))
    uvicorn.run(
        "main:app",
        host="0.0.0.0",
        port=port,
        reload=False
    )
