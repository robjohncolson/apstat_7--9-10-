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

SCOPES = ['https://www.googleapis.com/auth/drive']  # Full Drive access
SCRIPT_DIR = pathlib.Path(__file__).parent.resolve()
CREDENTIALS_FILE = SCRIPT_DIR / 'video-layup-39cd7d31cbe3.json'
WATCH_DIRECTORY = str(pathlib.Path(r"C:\Users\ColsonR\Videos\Screen Recordings").resolve())

# Set up logging
logging.basicConfig(
    filename='video_monitor.log',
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s'
)

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
        
        working_dir = os.path.basename(WATCH_DIRECTORY)
        
        # Try to find a similar folder name
        best_match = None
        for folder in folders:
            if working_dir.lower() in folder['name'].lower():
                best_match = folder
                break
        
        root = tk.Tk()
        root.withdraw()
        
        if best_match:
            msg = f"Upload to folder '{best_match['name']}'?\nClick 'Yes' to accept or 'No' to choose another folder"
            if messagebox.askyesno("Confirm Folder", msg):
                logging.info(f"Selected folder: {best_match['name']}")
                return best_match['id']
        
        # Show folder selection dialog
        folder_names = [f"{folder['name']}" for folder in folders]
        folder_choice = simpledialog.askstring(
            "Select Folder", 
            "Enter the name of the destination folder:",
            initialvalue=folder_names[0] if folder_names else ""
        )
        
        if folder_choice:
            for folder in folders:
                if folder['name'] == folder_choice:
                    logging.info(f"Selected folder: {folder['name']}")
                    return folder['id']
            
            error_msg = f"Folder '{folder_choice}' not found"
            logging.warning(error_msg)
            messagebox.showwarning("Warning", error_msg)
        
        return None

    def on_created(self, event):
        if not event.is_directory and event.src_path.lower().endswith('.mp4'):
            self.handle_new_video(event.src_path)
    
    def handle_new_video(self, filepath):
        logging.info(f"New video detected: {filepath}")
        
        root = tk.Tk()
        root.withdraw()
        
        suggested_name = os.path.basename(filepath)
        new_name = simpledialog.askstring("Rename Video", 
                                        "Enter new name for the video:",
                                        initialvalue=suggested_name)
        
        if new_name:
            if not new_name.lower().endswith('.mp4'):
                new_name += '.mp4'
            
            new_filepath = os.path.join(os.path.dirname(filepath), new_name)
            os.rename(filepath, new_filepath)
            logging.info(f"File renamed to: {new_name}")
            
            folder_id = self.suggest_folder()
            if folder_id:
                self.upload_to_drive(new_filepath, new_name, folder_id)
            else:
                logging.warning("Upload cancelled - no folder selected")
                messagebox.showwarning("Upload Cancelled", "No folder was selected for upload")

    def upload_to_drive(self, filepath, filename, folder_id):
        try:
            file_metadata = {
                'name': filename,
                'parents': [folder_id]
            }
            
            media = MediaFileUpload(
                filepath, 
                mimetype='video/mp4',
                resumable=True
            )
            
            # Create progress bar window
            progress_window = tk.Toplevel()
            progress_window.title("Uploading...")
            progress_window.geometry("300x150")
            
            # Center the window
            progress_window.geometry("+%d+%d" % (
                progress_window.winfo_screenwidth()/2 - 150,
                progress_window.winfo_screenheight()/2 - 75
            ))
            
            label = ttk.Label(progress_window, text=f"Uploading {filename}")
            label.pack(pady=10)
            
            progress_bar = ttk.Progressbar(
                progress_window, 
                orient="horizontal", 
                length=200, 
                mode="determinate"
            )
            progress_bar.pack(pady=20)
            
            # Start the upload
            request = self.service.files().create(
                body=file_metadata,
                media_body=media,
                fields='id, webViewLink'
            )
            
            response = None
            while response is None:
                status, response = request.next_chunk()
                if status:
                    progress_bar['value'] = int(status.progress() * 100)
                    progress_window.update()
                    label.config(text=f"Uploading {filename}: {int(status.progress() * 100)}%")
            
            progress_window.destroy()
            
            # Verify upload was successful
            if response and response.get('id'):
                # Show success message with link
                msg = (f"File uploaded successfully!\n"
                      f"Name: {filename}\n"
                      f"Link: {response['webViewLink']}\n\n"
                      f"Would you like to delete the local copy?")
                
                if messagebox.askyesno("Upload Complete", msg):
                    try:
                        os.remove(filepath)
                        logging.info(f"Local file deleted: {filepath}")
                    except Exception as e:
                        error_msg = f"Error deleting local file: {str(e)}"
                        logging.error(error_msg)
                        messagebox.showwarning("Warning", f"Could not delete local file: {error_msg}")
                
                logging.info(f"File uploaded successfully: {filename}")
                return response['id']
            
        except Exception as e:
            if 'progress_window' in locals():
                progress_window.destroy()
            error_msg = f"Error uploading file: {str(e)}"
            logging.error(error_msg)
            messagebox.showerror("Error", error_msg)
            return None

def main():
    watch_dir = pathlib.Path(WATCH_DIRECTORY)
    if not watch_dir.exists():
        print(f"Creating directory: {watch_dir}")
        watch_dir.mkdir(parents=True, exist_ok=True)
    
    logging.info(f"Starting video monitor service in: {watch_dir}")
    event_handler = VideoHandler()
    observer = Observer()
    observer.schedule(event_handler, str(watch_dir), recursive=False)
    observer.start()
    
    try:
        while True:
            time.sleep(1)
    except KeyboardInterrupt:
        observer.stop()
        logging.info("Video monitor service stopped")
    observer.join()

if __name__ == "__main__":
    main() 