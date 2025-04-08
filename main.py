import os
import asyncio
os.environ['PATH'] += os.pathsep + os.getcwd()  # Make ffmpeg work in Replit

import yt_dlp
import requests
from telegram import Update
from telegram.ext import ApplicationBuilder, MessageHandler, CommandHandler, ContextTypes, filters
from threading import Thread
from server import run

TOKEN = os.getenv("BOT_TOKEN")
CHANNEL_ID = os.getenv("CHANNEL_ID")

# Global operation tracking
current_operation = None
current_task = None

def download_video(url):
    global current_operation, current_task
    current_operation = "downloading"
    current_task = asyncio.current_task()
    # Check if URL tracking file exists
    last_url_file = "last_downloaded_url.txt"
    if os.path.exists(last_url_file):
        with open(last_url_file, 'r') as f:
            last_url = f.read().strip()
            if last_url == url and os.path.exists('downloaded_video.mp4'):
                # Return existing file if URLs match
                with yt_dlp.YoutubeDL() as ydl:
                    info = ydl.extract_info(url, download=False)
                    video_id = info.get("id")
                    title = info.get("title", "No Title")
                    thumb_path = f"thumb_{video_id}.jpg"
                    return 'downloaded_video.mp4', title, thumb_path if os.path.exists(thumb_path) else None

    ydl_opts = {
        'format': 'bestvideo+bestaudio/best',
        'outtmpl': 'downloaded_video.%(ext)s',
        'merge_output_format': 'mp4',
        'noplaylist': True,
    }

    # Save current URL
    with open(last_url_file, 'w') as f:
        f.write(url)

    with yt_dlp.YoutubeDL(ydl_opts) as ydl:
        info = ydl.extract_info(url, download=True)
        video_id = info.get("id")
        title = info.get("title", "No Title")
        ext = info.get("ext", "mp4")
        filename = ydl.prepare_filename(info)

        # Grab highest res thumbnail
        thumb_url = f"https://img.youtube.com/vi/{video_id}/maxresdefault.jpg"
        thumb_path = f"thumb_{video_id}.jpg"

        try:
            r = requests.get(thumb_url)
            if r.status_code == 200:
                with open(thumb_path, 'wb') as f:
                    f.write(r.content)
            else:
                thumb_path = None
        except:
            thumb_path = None

        return filename, title, thumb_path

# 👇 Handle incoming YouTube link
async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    global current_operation, current_task
    url = update.message.text.strip()
    await update.message.reply_text(f"📥 Downloading: {url}")
    current_task = asyncio.current_task()

    try:
        file_path, title, thumb_path = download_video(url)
        max_retries = 3
        retry_count = 0

        while retry_count < max_retries:
            try:
                status_msg = await update.message.reply_text(f"📤 Uploading... (Attempt {retry_count + 1}/{max_retries})")
                with open(file_path, 'rb') as video:
                    await context.bot.send_document(
                        chat_id=CHANNEL_ID,
                        document=video,
                        caption="📤 Uploaded existing video",
                        thumbnail=open(thumb_path, 'rb') if thumb_path else None,
                        read_timeout=1200,
                        write_timeout=1200,
                        connect_timeout=300
                    )
                await status_msg.edit_text("✅ Uploaded!")
                break
            except Exception as upload_error:
                retry_count += 1
                if retry_count >= max_retries:
                    raise upload_error
                await status_msg.edit_text(f"⚠️ Upload attempt {retry_count} failed, retrying...")

    except Exception as e:
        print("[ERROR]", e)
        await update.message.reply_text(f"❌ Upload failed: {e}")

# 👇 Manual re-upload if video already exists
async def upload_existing(update: Update, context: ContextTypes.DEFAULT_TYPE):
    video_path = "downloaded_video.mp4"
    thumb_files = [f for f in os.listdir() if f.startswith("thumb_") and f.endswith(".jpg")]
    thumb_path = thumb_files[0] if thumb_files else None

    if not os.path.exists(video_path):
        await update.message.reply_text("❌ No downloaded video found. Try sending a URL first.")
        return

    max_retries = 3
    retry_count = 0

    try:
        while retry_count < max_retries:
            try:
                status_msg = await update.message.reply_text(f"🔄 Starting upload (Attempt {retry_count + 1}/{max_retries})...")
                file_size = os.path.getsize(video_path) / (1024 * 1024)  # Size in MB
                if file_size > 50:  # If file is larger than 50MB
                    await status_msg.edit_text(f"⚠️ File size is {file_size:.1f}MB. Uploading in document mode...")
                    
                try:
                    await status_msg.edit_text(f"📤 Preparing to upload {file_size:.1f}MB...")
                    
                    # Create file-like object for streaming
                    # Simple progress tracking without async wrapper
                    with open(video_path, 'rb') as video:
                        total_size = os.path.getsize(video_path)
                        await context.bot.send_document(
                            chat_id=CHANNEL_ID,
                            document=video,
                            caption=f"📤 Video file ({file_size:.1f}MB)",
                            filename=os.path.basename(video_path),
                            read_timeout=7200,
                            write_timeout=7200,
                            connect_timeout=60,
                            disable_content_type_detection=True
                        )

                    # Create progress wrapper
                    progress_file = ProgressFileWrapper(video_path, os.path.getsize(video_path), status_msg)
                    
                    await context.bot.send_document(
                        chat_id=CHANNEL_ID,
                        document=progress_file,
                        caption=f"📤 Video file ({file_size:.1f}MB)",
                        filename=os.path.basename(video_path),
                        read_timeout=7200,
                        write_timeout=7200,
                        connect_timeout=60,
                        disable_content_type_detection=True
                    )
                    await status_msg.edit_text("✅ Upload successful!")
                    progress_file.close()
                except Exception as e:
                        await status_msg.edit_text(f"❌ Upload failed: {str(e)}\nTry with a smaller video file.")
                        raise e
                break
            except Exception as upload_error:
                retry_count += 1
                if retry_count >= max_retries:
                    raise upload_error
                await status_msg.edit_text(f"⚠️ Upload attempt {retry_count} failed, retrying...")
    except Exception as e:
        print("[UPLOAD ERROR]", e)
        await update.message.reply_text(f"❌ Upload failed: {e}")

# Command handlers
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    commands = """
Available commands:
/start - Show this help message
/upload - Upload existing video
/status - Check bot status
/end - Stop current operation
/clear_cache - Clear all downloaded files
    """
    await update.message.reply_text(commands)

async def status(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if os.path.exists('downloaded_video.mp4'):
        with open('last_downloaded_url.txt', 'r') as f:
            last_url = f.read().strip()
        status_msg = f"✅ Last downloaded video: {last_url}"
        if current_operation:
            status_msg += f"\nCurrent operation: {current_operation}"
        await update.message.reply_text(status_msg)
    else:
        await update.message.reply_text("❌ No video currently downloaded")

async def end_operation(update: Update, context: ContextTypes.DEFAULT_TYPE):
    global current_operation, current_task
    if current_operation and current_task:
        operation = current_operation
        try:
            current_task.cancel()
        except:
            pass
        current_operation = None
        current_task = None
        
        # Clean up temporary files
        if os.path.exists('downloaded_video.mp4.part'):
            os.remove('downloaded_video.mp4.part')
        await update.message.reply_text(f"🛑 Stopped {operation} operation")
    else:
        await update.message.reply_text("ℹ️ No operation in progress")

async def clear_cache(update: Update, context: ContextTypes.DEFAULT_TYPE):
    # Clear downloaded videos
    if os.path.exists('downloaded_video.mp4'):
        os.remove('downloaded_video.mp4')
    if os.path.exists('downloaded_video.mp4.part'):
        os.remove('downloaded_video.mp4.part')
    
    # Clear thumbnails
    for file in os.listdir():
        if file.startswith('thumb_') and file.endswith('.jpg'):
            os.remove(file)
            
    # Clear URL tracking
    if os.path.exists('last_downloaded_url.txt'):
        os.remove('last_downloaded_url.txt')
        
    await update.message.reply_text("🧹 Cleared all downloaded files and thumbnails")

# 🔧 Set up bot
app = ApplicationBuilder().token(TOKEN).build()

# 🔄 Handlers
app.add_handler(CommandHandler("start", start))
app.add_handler(CommandHandler("status", status))
app.add_handler(CommandHandler("upload", upload_existing))
app.add_handler(CommandHandler("end", end_operation))
app.add_handler(CommandHandler("clear_cache", clear_cache))
app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_message))

# 🌐 Keep-alive server for Replit
Thread(target=run).start()
print("✅ Bot is running...")
app.run_polling()