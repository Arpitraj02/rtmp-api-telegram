# Live Stream Control Center - Deployment Guide

## 🚀 Quick Deployment to Render.com

### Prerequisites
- A Render.com account (free tier works)
- FFmpeg must be available on the server
- RTMP credentials from Telegram

### Step 1: Prepare Your Repository
1. Create a new GitHub repository
2. Add these files to your repository:
   - `main.py`
   - `requirements.txt`
   - `.gitignore` (optional, see below)

**Recommended `.gitignore`:**
```
__pycache__/
*.py[cod]
*$py.class
*.so
.Python
videos/
settings.json
queue.json
.env
```

### Step 2: Deploy on Render.com

1. **Log in to Render.com** and click "New +" → "Web Service"

2. **Connect your GitHub repository**

3. **Configure the service:**
   - **Name:** `stream-control-center` (or your choice)
   - **Environment:** `Python 3`
   - **Build Command:** `pip install -r requirements.txt`
   - **Start Command:** `python main.py`
   - **Instance Type:** `Free` or `Starter` (recommended for streaming)

4. **Add Environment Variables:**
   - Click "Advanced" → "Add Environment Variable"
   - Add: `PORT` = `10000` (Render's default, but the app auto-detects this)

5. **Install FFmpeg on Render:**
   - Render's default Python environment doesn't include FFmpeg
   - You need to add a custom build script or use a Docker deployment
   
   **Option A: Using Shell Script (Add to repository)**
   
   Create `render-build.sh`:
   ```bash
   #!/usr/bin/env bash
   # Install FFmpeg
   apt-get update
   apt-get install -y ffmpeg
   
   # Install Python dependencies
   pip install -r requirements.txt
   ```
   
   Then update Render build command to: `./render-build.sh`
   
   **Option B: Using Dockerfile (Recommended)**
   
   Create `Dockerfile`:
   ```dockerfile
   FROM python:3.11-slim
   
   # Install FFmpeg
   RUN apt-get update && apt-get install -y ffmpeg && rm -rf /var/lib/apt/lists/*
   
   # Set working directory
   WORKDIR /app
   
   # Copy requirements and install
   COPY requirements.txt .
   RUN pip install --no-cache-dir -r requirements.txt
   
   # Copy application
   COPY main.py .
   
   # Create videos directory
   RUN mkdir -p videos
   
   # Expose port
   EXPOSE 10000
   
   # Run application
   CMD ["python", "main.py"]
   ```
   
   Then on Render, select "Docker" as environment instead of "Python 3"

6. **Click "Create Web Service"**

### Step 3: Verify Deployment

Once deployed, Render will provide you with a URL like:
`https://stream-control-center.onrender.com`

Test the API:
```bash
curl https://your-app-name.onrender.com/
```

Expected response:
```json
{
  "message": "Live Stream Control Center API",
  "status": "online",
  "version": "1.0.0"
}
```

## 🔧 Configuration

### Setting Up RTMP Credentials

1. **Using the API:**
```bash
curl -X POST https://your-app-name.onrender.com/settings \
  -H "Content-Type: application/json" \
  -d '{
    "rtmp_url": "rtmp://your-telegram-rtmp-url",
    "stream_key": "your_stream_key",
    "resolution": "1920x1080",
    "bitrate": 2500,
    "fps": 30
  }'
```

2. **Using your React frontend:**
   - Update `API_BASE_URL` to point to your Render URL
   - Use the settings form in the frontend

## 📁 File Structure

After deployment, your server will have:
```
/app
├── main.py              # Main application
├── requirements.txt     # Python dependencies
├── videos/             # Uploaded videos (auto-created)
├── settings.json       # RTMP settings (auto-created)
└── queue.json          # Stream queue (auto-created)
```

## 🎥 Getting Telegram RTMP Credentials

1. Open Telegram Desktop or Web
2. Start a live stream in your channel/group
3. Select "Stream with RTMP"
4. Copy the RTMP URL and Stream Key
5. Use these in your settings

**Important:** Telegram RTMP URLs are temporary and change each stream session. You'll need to update settings before each stream.

## 🔐 Security Considerations

For production use, consider:

1. **Add Authentication:** Protect endpoints with API keys or JWT tokens
2. **Rate Limiting:** Prevent abuse of upload endpoint
3. **File Size Limits:** Configure max upload size in FastAPI
4. **HTTPS Only:** Render provides this automatically
5. **Environment Variables:** Store sensitive settings as environment variables

Example with API Key protection:
```python
from fastapi import Header, HTTPException

async def verify_api_key(x_api_key: str = Header(...)):
    if x_api_key != os.environ.get("API_KEY"):
        raise HTTPException(status_code=403, detail="Invalid API key")
    return x_api_key

# Add to protected endpoints
@app.post("/stream/start", dependencies=[Depends(verify_api_key)])
async def start_stream():
    ...
```

## 🐛 Troubleshooting

### FFmpeg Not Found
- Ensure FFmpeg is installed in your build process
- Check Render logs: Dashboard → Your Service → Logs
- Verify FFmpeg: Add endpoint to check `subprocess.run(['ffmpeg', '-version'])`

### Stream Fails to Start
- Check RTMP credentials are correct
- Verify video files exist in `/videos` directory
- Check Render logs for FFmpeg errors
- Ensure sufficient resources (upgrade from Free tier if needed)

### Uploads Failing
- Check file size limits (Render Free tier has limits)
- Verify disk space is available
- Check CORS settings if uploading from browser

### Queue Not Persisting
- Files are stored in `queue.json` and `settings.json`
- On Render Free tier, these reset on each deploy
- Upgrade to paid plan for persistent disk or use external storage (S3)

## 📊 Monitoring

Monitor your stream:
```bash
# Check status
curl https://your-app-name.onrender.com/status

# List videos
curl https://your-app-name.onrender.com/videos

# View queue
curl https://your-app-name.onrender.com/queue
```

## 🚀 Advanced: Persistent Storage with AWS S3

For production, consider storing videos in S3:

1. Install `boto3`: Add to `requirements.txt`
2. Set AWS credentials as environment variables
3. Modify upload/download logic to use S3
4. This prevents data loss on Render restarts

## 📝 Notes

- **Free Tier Limitations:** Render Free tier spins down after inactivity. First request may be slow.
- **Persistent Disk:** Free tier doesn't include persistent disk. Videos are lost on restart.
- **Resource Usage:** Streaming is CPU-intensive. Monitor usage and upgrade if needed.
- **Concurrent Streams:** Current implementation supports one stream at a time.

## 🆘 Support

If you encounter issues:
1. Check Render logs in dashboard
2. Review FFmpeg output in logs
3. Test endpoints individually with curl
4. Verify RTMP credentials with Telegram

## 🎉 Success!

Your Live Stream Control Center should now be running on Render.com. Connect your React frontend and start streaming!
