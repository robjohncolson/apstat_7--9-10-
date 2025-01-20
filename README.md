# Video Monitor

A Python-based utility that automatically monitors a directory for new screen recordings and uploads them to Google Drive.

## Features

- Automatic detection of new screen recordings
- Seamless upload to Google Drive
- Folder selection in Google Drive
- Automatic file organization (moves processed files to "Uploaded Videos")
- Robust error handling and retry mechanisms
- Logging system for monitoring operations

## Requirements

- Python 3.x
- Google Drive API credentials
- Required Python packages (see requirements.txt)

## Setup

1. Ensure you have Python 3.x installed
2. Install required packages:
   ```bash
   pip install -r requirements.txt
   ```
3. Set up Google Drive API credentials:
   - Place your service account credentials file in the project directory
   - Ensure the service account has necessary permissions on Google Drive

## Usage

Run the video monitor:
```bash
python video_monitor.py
```

The monitor will:
1. Watch for new screen recordings
2. Upload them to the selected Google Drive folder
3. Move processed files to the "Uploaded Videos" folder
4. Log all operations to video_monitor.log

## Configuration

The monitor is configured to:
- Watch the Windows Screen Recordings directory
- Create an "Uploaded Videos" folder for processed files
- Maintain a detailed log of all operations
- Handle file locking and access issues gracefully

## Logging

Logs are written to `video_monitor.log` and include:
- File detection events
- Upload progress
- Error conditions
- File movement operations

## Known Issues

- File locking can occasionally prevent immediate file movement after upload
- OAuth client version compatibility warning (non-critical) 