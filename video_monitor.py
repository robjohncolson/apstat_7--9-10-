from watchdog.observers import Observer
from watchdog.events import FileSystemEventHandler
from google.oauth2.credentials import Credentials
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

SCOPES = ['https://www.googleapis.com/auth/drive.file']
WATCH_DIRECTORY = str(pathlib.Path(r"C:\Users\ColsonR\Downloads\apstat\apstat_unit7\apstat_7-{9,10}").resolve())

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
        creds = None
        if os.path.exists('token.pickle'):
            with open('token.pickle', 'rb') as token:
                creds = pickle.load(token)
        
        if not creds or not creds.valid:
            if creds and creds.expired and creds.refresh_token:
                creds.refresh(Request())
            else:
                flow = InstalledAppFlow.from_client_secrets_file(
                    'credentials.json', SCOPES)
                creds = flow.run_local_server(port=0)
            
            with open('token.pickle', 'wb') as token:
                pickle.dump(creds, token)

        self.service = build('drive', 'v3', credentials=creds)

    def get_drive_folders(self):
        results = self.service.files().list(
            q="mimeType='application/vnd.google-apps.folder'",
            fields="files(id, name)").execute()
        return results.get('files', [])

    def suggest_folder(self):
        folders = self.get_drive_folders()
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
                return best_match['id']
        
        # Show folder selection dialog
        folder_names = [f"{folder['name']}" for folder in folders]
        folder_choice = simpledialog.askstring(
            "Select Folder", 
            "Enter the name of the destination folder:",
            initialvalue=folder_names[0] if folder_names else ""
        )
        
        for folder in folders:
            if folder['name'] == folder_choice:
                return folder['id']
        
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
            media = MediaFileUpload(filepath, resumable=True)
            
            file = self.service.files().create(
                body=file_metadata,
                media_body=media,
                fields='id,name,webViewLink'
            ).execute()
            
            success_msg = f"File uploaded successfully!\nName: {file.get('name')}\nLink: {file.get('webViewLink')}"
            logging.info(f"File uploaded successfully. ID: {file.get('id')}")
            
            root = tk.Tk()
            root.withdraw()
            messagebox.showinfo("Upload Complete", success_msg)
            
        except Exception as e:
            error_msg = f"Error uploading file: {str(e)}"
            logging.error(error_msg)
            messagebox.showerror("Upload Error", error_msg)

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