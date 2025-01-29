from watchdog.observers import Observer
from watchdog.events import FileSystemEventHandler
from google.oauth2.service_account import Credentials
from google_auth_oauthlib.flow import InstalledAppFlow
from google.auth.transport.requests import Request
from googleapiclient.discovery import build
from googleapiclient.http import MediaFileUpload
import os
import pickle
import time
import tkinter as tk
from tkinter import simpledialog, messagebox
import logging
from datetime import datetime
import pathlib
import sys
from tqdm import tqdm
from tkinter import ttk
import threading
import signal
from tenacity import retry, stop_after_attempt, wait_exponential, retry_if_exception_type
import ssl
import httplib2

SCOPES = ['https://www.googleapis.com/auth/drive']  # Full Drive access
SCRIPT_DIR = pathlib.Path(__file__).parent.resolve()
CREDENTIALS_FILE = SCRIPT_DIR / 'video-layup-39cd7d31cbe3.json'
WATCH_DIRECTORY = str(pathlib.Path(r"C:\Users\ColsonR\Videos\Screen Recordings").resolve())
RETRY_ATTEMPTS = 3
MOVE_RETRY_DELAY = 30  # seconds
UPLOAD_CHUNK_SIZE = 256 * 1024  # 256KB

# Set up logging
logging.basicConfig(
    filename='video_monitor.log',
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s'
)

httplib2.RETRIES = 3
ssl_context = ssl.create_default_context()
ssl_context.set_ciphers('DEFAULT@SECLEVEL=1')
ssl_context.minimum_version = ssl.TLSVersion.TLSv1_2

class VideoHandler(FileSystemEventHandler):
    def __init__(self):
        self.service = None
        self.setup_drive_service()

    def setup_drive_service(self):
        while True:
            try:
                creds = Credentials.from_service_account_file(
                    str(CREDENTIALS_FILE),
                    scopes=SCOPES  # Using the broader scope
                )
                self.service = build('drive', 'v3', credentials=creds)
                logging.info("Successfully set up Google Drive service")
                break
            except FileNotFoundError:
                error_msg = f"\nError: Service account credentials file not found at: {CREDENTIALS_FILE}"
                logging.error(error_msg)
                print(error_msg)
                if not messagebox.askretrycancel("Error", "Credentials file not found. Would you like to try again?"):
                    sys.exit(1)
            except Exception as e:
                error_msg = f"\nError setting up Google Drive service: {str(e)}"
                logging.error(error_msg)
                print(error_msg)
                if not messagebox.askretrycancel("Error", "Failed to set up Drive service. Would you like to try again?"):
                    sys.exit(1)

    def get_drive_folders(self):
        while True:
            try:
                # First verify the service account
                about = self.service.about().get(fields="user").execute()
                logging.info(f"Authenticated as: {about.get('user', {}).get('emailAddress')}")
                
                results = self.service.files().list(
                    q="mimeType='application/vnd.google-apps.folder'",
                    fields="files(id, name)",
                    pageSize=100  # Increase page size to ensure we get all folders
                ).execute()
                folders = results.get('files', [])
                
                if not folders:
                    logging.warning("No folders found in Google Drive")
                    print("Warning: No folders found in Google Drive")
                    email = about.get('user', {}).get('emailAddress', 'unknown')
                    if not messagebox.askretrycancel("Warning", 
                        f"No folders found. Please share a folder with {email} and click Retry."):
                        return []
                    continue
                
                logging.info(f"Found {len(folders)} folders in Google Drive")
                for folder in folders:
                    logging.info(f"Found folder: {folder['name']}")
                return folders
                
            except Exception as e:
                error_msg = f"Error getting drive folders: {str(e)}"
                logging.error(error_msg)
                print(f"\n{error_msg}")
                if not messagebox.askretrycancel("Error", 
                    "Failed to get Drive folders. Check the log file for details. Would you like to try again?"):
                    return []

    def suggest_folder(self):
        folders = self.get_drive_folders()
        if not folders:
            error_msg = "No accessible folders found. Please share at least one folder with the service account."
            logging.error(error_msg)
            messagebox.showerror("Error", error_msg)
            return None
        
        root = tk.Tk()
        root.withdraw()
        
        # Create folder selection dialog
        dialog = tk.Toplevel(root)
        dialog.title("Select Upload Folder")
        dialog.geometry("300x400")
        
        # Center the dialog
        dialog.geometry("+%d+%d" % (
            root.winfo_screenwidth()/2 - 150,
            root.winfo_screenheight()/2 - 200
        ))
        
        result = {'value': None}
        
        # Create Treeview
        tree = ttk.Treeview(dialog, show='tree')
        tree.pack(fill=tk.BOTH, expand=True, padx=10, pady=10)
        
        # Add scrollbar
        scrollbar = ttk.Scrollbar(dialog, orient="vertical", command=tree.yview)
        scrollbar.pack(side=tk.RIGHT, fill=tk.Y)
        tree.configure(yscrollcommand=scrollbar.set)
        
        # Populate tree with folders
        for folder in folders:
            tree.insert('', 'end', folder['id'], text=folder['name'])
        
        def on_select():
            selected = tree.selection()
            if selected:
                result['value'] = selected[0]  # This will be the folder ID
            dialog.destroy()
        
        def on_timeout():
            if dialog.winfo_exists():
                # Select first folder as default
                first_id = tree.get_children()[0]
                result['value'] = first_id
                dialog.destroy()
        
        # Add Select button
        ttk.Button(dialog, text="Select", command=on_select).pack(pady=10)
        
        # Start timeout
        dialog.after(5000, on_timeout)
        
        dialog.transient(root)
        dialog.grab_set()
        root.wait_window(dialog)
        
        if result['value']:
            selected_folder = next((f for f in folders if f['id'] == result['value']), None)
            if selected_folder:
                logging.info(f"Selected folder: {selected_folder['name']}")
                return result['value']
        
        return None

    def on_created(self, event):
        if not event.is_directory and event.src_path.lower().endswith('.mp4'):
            self.handle_new_video(event.src_path)
    
    def handle_new_video(self, filepath):
        try:
            logging.info(f"New video detected: {filepath}")
            
            # Wait for file to stabilize
            previous_size = -1
            current_size = os.path.getsize(filepath)
            
            while previous_size != current_size:
                time.sleep(1)  # Wait 1 second
                previous_size = current_size
                current_size = os.path.getsize(filepath)
                logging.info(f"Waiting for file to finish writing: {current_size/1024/1024:.1f} MB")
            
            logging.info("File size stabilized, proceeding with upload")
            
            # Get the folder ID if we don't have it
            if not hasattr(self, 'folder_id') or not self.folder_id:
                self.folder_id = self.suggest_folder()
                if not self.folder_id:
                    return
            
            file_name = os.path.basename(filepath)
            
            # Prompt for new filename
            new_name = simpledialog.askstring(
                "Rename File", 
                "Enter new filename (or leave blank to keep current):",
                initialvalue=file_name
            )
            
            if new_name:
                file_name = new_name if new_name.endswith('.mp4') else f"{new_name}.mp4"
            
            # Upload the file
            self.upload_to_drive(filepath, file_name, self.folder_id)
            
        except Exception as e:
            error_msg = f"Error processing new video: {str(e)}"
            logging.error(error_msg)
            messagebox.showerror("Error", error_msg)

    def try_delete_file(self, filepath, max_attempts=3):
        for attempt in range(max_attempts):
            try:
                # Wait with increasing delay
                time.sleep(2 * (attempt + 1))
                os.remove(filepath)
                logging.info(f"Local file deleted: {filepath}")
                return True
            except Exception as e:
                logging.warning(f"Deletion attempt {attempt + 1} failed: {str(e)}")
        return False

    def upload_to_drive(self, filepath, filename, folder_id):
        @retry(
            stop=stop_after_attempt(3),
            wait=wait_exponential(multiplier=1, min=4, max=10),
            retry=retry_if_exception_type((ssl.SSLError, IOError))
        )
        def upload_with_retry(file_metadata, media):
            request = self.service.files().create(
                body=file_metadata,
                media_body=media,
                fields='id, webViewLink',
                timeout=30
            )
            
            response = None
            last_progress = 0
            
            while response is None:
                try:
                    status, response = request.next_chunk()
                    if status:
                        progress = int(status.progress() * 100)
                        if progress >= last_progress + 10:
                            logging.info(f"Upload progress: {progress}%")
                            last_progress = progress - (progress % 10)
                except ssl.SSLError as e:
                    logging.warning(f"SSL Error during upload: {str(e)}")
                    raise
            return response

        try:
            file_metadata = {
                'name': filename,
                'parents': [folder_id]
            }
            
            media = MediaFileUpload(
                filepath,
                mimetype='video/mp4',
                resumable=True,
                chunksize=256 * 1024  # 256KB chunks
            )
            
            logging.info(f"Starting upload of {filename}")
            response = upload_with_retry(file_metadata, media)
            
            if response and response.get('id'):
                msg = (f"File uploaded successfully!\n"
                      f"Name: {filename}\n"
                      f"Link: {response['webViewLink']}")
                
                messagebox.showinfo("Upload Complete", msg)
                
                # Try to move file to processed folder
                if self.move_to_processed_folder(filepath, "Uploaded Videos"):
                    logging.info(f"File moved to processed folder: {filename}")
                else:
                    error_msg = "Could not move file to processed folder - it may be in use. Will try again later."
                    logging.warning(error_msg)
                    messagebox.showwarning("Warning", error_msg)
                    # Schedule another attempt in 30 seconds
                    threading.Timer(30.0, 
                        lambda: self.move_to_processed_folder(filepath, "Uploaded Videos")
                    ).start()
                
                logging.info(f"File uploaded successfully: {filename}")
                return response['id']
            
        except Exception as e:
            error_msg = f"Error uploading file: {str(e)}"
            logging.error(error_msg)
            messagebox.showerror("Error", error_msg)
            return None

    def move_to_processed_folder(self, filepath, target_folder_name):
        try:
            import win32file
            import win32con
            import pywintypes
            
            # Create processed folder with target folder name
            processed_dir = os.path.join(os.path.dirname(filepath), target_folder_name)
            if not os.path.exists(processed_dir):
                os.makedirs(processed_dir)
                logging.info(f"Created processed folder: {processed_dir}")
            
            # Move file to processed folder using Windows API
            filename = os.path.basename(filepath)
            new_path = os.path.join(processed_dir, filename)
            
            # Try to unlock the file first
            try:
                handle = win32file.CreateFile(
                    filepath,
                    win32con.GENERIC_WRITE,
                    0,  # No sharing
                    None,
                    win32con.OPEN_EXISTING,
                    win32con.FILE_ATTRIBUTE_NORMAL,
                    None
                )
                win32file.CloseHandle(handle)
            except pywintypes.error:
                logging.warning("Could not unlock file, will try moving anyway")
            
            # Try the move
            win32file.MoveFile(filepath, new_path)
            logging.info(f"Moved {filename} to {processed_dir}")
            return True
            
        except Exception as e:
            logging.error(f"Error moving file to processed folder: {str(e)}")
            return False

    def handle_existing_videos(self):
        existing_videos = [f for f in os.listdir(WATCH_DIRECTORY) 
                          if f.lower().endswith('.mp4')]
        
        if not existing_videos:
            return
        
        msg = f"Found {len(existing_videos)} existing videos. Would you like to upload them?"
        if messagebox.askyesno("Existing Videos", msg):
            for video in existing_videos:
                filepath = os.path.join(WATCH_DIRECTORY, video)
                self.handle_new_video(filepath)
        else:
            folder_name = simpledialog.askstring(
                "Create Folder", 
                "Enter folder name for existing videos:",
                initialvalue="Unprocessed Videos"
            )
            if folder_name:
                processed_dir = os.path.join(WATCH_DIRECTORY, folder_name)
                if not os.path.exists(processed_dir):
                    os.makedirs(processed_dir)
                for video in existing_videos:
                    old_path = os.path.join(WATCH_DIRECTORY, video)
                    new_path = os.path.join(processed_dir, video)
                    os.rename(old_path, new_path)
                logging.info(f"Moved {len(existing_videos)} videos to {folder_name}")

def cleanup():
    logging.info("Shutting down video monitor...")
    try:
        # Get current process ID
        pid_file = 'video_monitor.pid'
        
        # Check if another instance is running
        if os.path.exists(pid_file):
            with open(pid_file, 'r') as f:
                old_pid = int(f.read())
            try:
                # Try to terminate old process
                os.kill(old_pid, signal.SIGTERM)
                logging.info(f"Terminated old process: {old_pid}")
            except ProcessLookupError:
                pass
            
        # Cancel any pending move operations
        for thread in threading.enumerate():
            if thread.name.startswith('move_retry_'):
                thread.cancel()
                
    except Exception as e:
        logging.error(f"Error during cleanup: {str(e)}")
    finally:
        # Remove PID file
        if os.path.exists('video_monitor.pid'):
            os.remove('video_monitor.pid')
        logging.info("Shutdown complete")
        sys.exit(0)

def signal_handler(signum, frame):
    logging.info(f"Received signal {signum}")
    cleanup()

def main():
    # Check for existing instance
    pid_file = 'video_monitor.pid'
    if os.path.exists(pid_file):
        with open(pid_file, 'r') as f:
            old_pid = int(f.read())
        try:
            os.kill(old_pid, 0)  # Check if process exists
            logging.error(f"Another instance is already running (PID: {old_pid})")
            messagebox.showerror("Error", "Another instance of Video Monitor is already running")
            sys.exit(1)
        except OSError:
            # Process not found, safe to continue
            pass
    
    # Write current PID
    with open(pid_file, 'w') as f:
        f.write(str(os.getpid()))
    
    # Register signal handlers
    signal.signal(signal.SIGINT, signal_handler)
    signal.signal(signal.SIGTERM, signal_handler)
    
    event_handler = VideoHandler()
    event_handler.handle_existing_videos()
    
    observer = Observer()
    observer.schedule(event_handler, WATCH_DIRECTORY, recursive=False)
    observer.start()
    
    try:
        while True:
            time.sleep(1)
    except KeyboardInterrupt:
        logging.info("Keyboard interrupt received")
    except Exception as e:
        logging.error(f"Unexpected error: {str(e)}")
    finally:
        logging.info("Stopping observer...")
        observer.stop()
        observer.join()
        cleanup()

if __name__ == '__main__':
    main() 