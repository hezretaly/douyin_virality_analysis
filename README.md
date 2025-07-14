# Douyin Virality Analysis API Documentation

This document provides an overview and explanation of the Python FastAPI application designed to discover, analyze, and download viral videos from Douyin (the Chinese version of TikTok). The API integrates with Google Drive, Google Sheets, and external APIs (Apify and RapidAPI) to perform four main tasks: discovering top creators, updating follower counts, generating virality reports, and downloading videos.

## Table of Contents
1. [Overview](#overview)
2. [Dependencies](#dependencies)
3. [Environment Setup](#environment-setup)
4. [API Endpoints](#api-endpoints)
   - [Discover and Save Creators](#discover-and-save-creators)
   - [Update Follower Counts](#update-follower-counts)
   - [Analyze and Generate Report](#analyze-and-generate-report)
   - [Download Videos to Drive](#download-videos-to-drive)
5. [Helper Functions](#helper-functions)
6. [Pydantic Models](#pydantic-models)
7. [Error Handling](#error-handling)
8. [Logging](#logging)

## Overview

The API is built using **FastAPI** and provides a four-step workflow for analyzing viral content on Douyin:

1. **Discover and Save Creators**: Scrapes videos based on search terms, calculates virality velocity, identifies top creators, and saves them to a Google Sheet.
2. **Update Follower Counts**: Updates missing follower counts for creators listed in a Google Sheet.
3. **Analyze and Generate Report**: Analyzes recent videos from creators in a Google Sheet, calculates virality scores, and generates a report in a new sheet.
4. **Download Videos to Drive**: Downloads specified videos and uploads them to a timestamped folder in Google Drive.

The application uses environment variables for sensitive data (e.g., API keys) and integrates with Google APIs for Drive and Sheets operations. It also employs **Pydantic** for request/response validation and **httpx** for asynchronous HTTP requests.

## Dependencies

The application relies on the following Python libraries:

```python
import json
import asyncio
from datetime import datetime, timezone
from typing import List, Dict, Any, Optional
from collections import defaultdict
import io
import logging
from pydantic import BaseModel, Field, HttpUrl
from fastapi import FastAPI, HTTPException, Security, Header
from fastapi.security import APIKeyHeader
import httpx
import os
from dotenv import load_dotenv
from google.oauth2.service_account import Credentials
from googleapiclient.discovery import build
from googleapiclient.http import MediaInMemoryUpload
from googleapiclient.errors import HttpError as GoogleHttpError
import gspread
```

- **FastAPI**: For building the API.
- **Pydantic**: For request/response data validation.
- **httpx**: For asynchronous HTTP requests to external APIs.
- **gspread**: For interacting with Google Sheets.
- **google-api-python-client**: For interacting with Google Drive.
- **python-dotenv**: For loading environment variables.
- **logging**: For logging application events.

## Environment Setup

Environment variables are loaded using `dotenv`. The following variables are required:

- `API_KEY_SECRET`: The API key for securing endpoints.
- `GOOGLE_CREDENTIALS_PATH`: Path to the Google service account credentials JSON file.
- `APIFY_TOKEN`: Token for the Apify Douyin scraper API.
- `RAPIDAPI_KEY`: Key for the RapidAPI Douyin Media API.

Example `.env` file:

```plaintext
API_KEY_SECRET=your_api_key
GOOGLE_CREDENTIALS_PATH=/path/to/credentials.json
APIFY_TOKEN=your_apify_token
RAPIDAPI_KEY=your_rapidapi_key
```

Load the environment variables at the start of the application:

```python
load_dotenv()
```

## API Endpoints

The API is initialized with metadata:

```python
app = FastAPI(
    title="Douyin Virality Analysis API",
    description="A four-step API to discover, analyze, and download top viral videos.",
    version="3.0.0"
)
```

All endpoints require an API key passed via the `x-api-key` header, validated by the `get_api_key` dependency.

### Discover and Save Creators

**Endpoint**: `POST /discover_and_save_creators`

**Description**: Scrapes videos using the Apify Douyin scraper, calculates virality velocity, identifies top creators, and saves new creators to a Google Sheet.

**Request Model**:

```python
class DiscoverAndSaveRequest(BaseModel):
    search_terms: List[str] = Field(..., description="List of keywords to search for videos.")
    spreadsheet_id: str = Field(..., description="The unique ID of the target Google Spreadsheet.")
    sheet_name: str = Field(..., description="The name of the worksheet to save creator data to.")
    max_videos_per_term: int = Field(100, description="Max videos to scrape per search term.")
    top_creators_to_rank: int = Field(20, description="The number of top creators to identify and save.")
```

**Response Model**:

```python
class DiscoverAndSaveResponse(BaseModel):
    message: str
    new_creators_added: int
    top_ranked_sec_uids: List[str] = Field(..., description="The ranked list of secUids identified in this run.")
```

**Workflow**:
1. Sends a request to the Apify API to scrape videos based on `search_terms`.
2. Calculates virality velocity for each video: `(0.5 * likes + 1.5 * comments + 2.0 * shares + 1.0 * collects) / video_age_in_hours`.
3. Sorts videos by velocity and selects the top creators (based on `top_creators_to_rank`).
4. Appends new creators to the specified Google Sheet, avoiding duplicates.

### Update Follower Counts

**Endpoint**: `POST /update_follower_counts`

**Description**: Scans a Google Sheet for creators with missing follower counts, fetches the counts via the RapidAPI Douyin Media API, and updates the sheet.

**Request Model**:

```python
class UpdateFollowersRequest(BaseModel):
    spreadsheet_id: str = Field(..., description="The unique ID of the target Google Spreadsheet.")
    sheet_name: str = Field(..., description="The name of the worksheet containing the creator data.")
```

**Response Model**:

```python
class UpdateFollowersResponse(BaseModel):
    message: str
    users_checked: int
    users_updated: int
    users_failed: int
```

**Workflow**:
1. Reads the Google Sheet to identify creators with empty `Follower Count` cells.
2. Fetches follower counts using the RapidAPI endpoint.
3. Updates the sheet with the fetched counts in a batch operation.

### Analyze and Generate Report

**Endpoint**: `POST /analyze_and_generate_report`

**Description**: Fetches recent videos for up to 20 creators from a Google Sheet, calculates a detailed virality score, and generates a sorted report in a new sheet.

**Request Model**:

```python
class AnalyzeAndReportRequest(BaseModel):
    spreadsheet_id: str = Field(..., description="The unique ID of the source Google Spreadsheet.")
    sheet_name: str = Field(..., description="The name of the sheet containing the user list.")
```

**Response Model**:

```python
class AnalyzeAndReportResponse(BaseModel):
    message: str
    videos_processed: int
    report_sheet_url: str
```

**Workflow**:
1. Reads the last 20 creators from the specified sheet.
2. Fetches up to 10 recent videos per creator via RapidAPI.
3. Calculates a virality score: `W1 * virality_velocity + W2 * engagement_to_follower_ratio`, where:
   - `virality_velocity = (0.5 * likes + 1.5 * comments + 2.0 * shares + 1.0 * collects) / video_age_in_hours`
   - `engagement_to_follower_ratio = (0.3 * likes + 1.8 * comments + 2.5 * shares + 1.2 * collects + 3.0 * recommends) / log(follower_count + 1)`
   - `W1 = 0.4`, `W2 = 0.6`
4. Creates a new sheet with a timestamped name and saves the sorted report.

### Download Videos to Drive

**Endpoint**: `POST /download_videos_to_drive`

**Description**: Downloads specified videos by their IDs and uploads them to a new timestamped folder in Google Drive.

**Request Model**:

```python
class DownloadRequest(BaseModel):
    parent_folder_id: str = Field(..., description="The ID of the parent folder in Google Drive where the new folder will be created. Must be in a Shared Drive.")
    video_ids: List[str] = Field(..., description="A list of Douyin video IDs (aweme_id) to download.")
```

**Response Model**:

```python
class DownloadResponse(BaseModel):
    message: str
    new_folder_url: str
    download_results: List[DownloadResult]

class DownloadResult(BaseModel):
    video_id: str
    status: str
    drive_link: Optional[str] = None
    error_detail: Optional[str] = None
```

**Workflow**:
1. Creates a timestamped folder in the specified Google Drive parent folder.
2. For each video ID, fetches the no-watermark download link via RapidAPI.
3. Downloads the video and uploads it to the new Drive folder.
4. Returns the folder URL and a list of download results.

## Helper Functions

### Google Drive Integration

- **get_drive_service**: Initializes the Google Drive API service using service account credentials.
  
```python
def get_drive_service():
    ```Builds and returns an authenticated Google Drive API service object.```
    try:
        credentials_path = os.getenv("GOOGLE_CREDENTIALS_PATH")
        if not credentials_path or not os.path.exists(credentials_path):
            raise FileNotFoundError("Google credentials file not found or path is incorrect.")
        scopes = ['https://www.googleapis.com/auth/drive.file']
        creds = Credentials.from_service_account_file(credentials_path, scopes=scopes)
        return build('drive', 'v3', credentials=creds, cache_discovery=False)
    except Exception as e:
        logging.error(f"[Drive Init] Failed to build Google Drive service: {e}")
        raise HTTPException(status_code=500, detail="Could not initialize Google Drive service.")
```

- **create_drive_folder**: Creates a folder in Google Drive with support for Shared Drives.

- **upload_data_to_drive**: Uploads in-memory data (e.g., video content) to a specified Drive folder.

### Google Sheets Integration

- **get_gspread_client**: Initializes the gspread client for Google Sheets operations.

```python
def get_gspread_client():
    ```Builds and returns a gspread client object.```
    try:
        credentials_path = os.getenv("GOOGLE_CREDENTIALS_PATH")
        if not credentials_path or not os.path.exists(credentials_path):
            raise FileNotFoundError("Google credentials file not found.")
        return gspread.service_account(filename=credentials_path)
    except Exception as e:
        logging.error(f"[Gspread Init] Failed to build client: {e}")
        raise HTTPException(status_code=500, detail="Could not initialize Google Sheets client.")
```

## Pydantic Models

Pydantic models are used for request and response validation, ensuring type safety and clear documentation. Each endpoint has a corresponding request and response model, as described above.

## Error Handling

The application uses **HTTPException** to handle errors gracefully, providing detailed error messages for issues such as:
- Invalid or missing API keys.
- Google Drive/Sheets initialization failures.
- External API request failures (Apify, RapidAPI).
- Missing spreadsheet/sheet or invalid data.

Example error handling:

```python
try:
    response = await client.post(APIFY_API_URL, params=api_params, json=api_payload)
    response.raise_for_status()
except httpx.HTTPStatusError as e:
    logging.error(f"Apify API request failed with status {e.response.status_code}: {e.response.text}")
    raise HTTPException(
        status_code=502,
        detail=f"Failed to fetch data from Apify API. Status: {e.response.status_code}."
    )
```

## Logging

Logging is configured to capture application events at the INFO level and above:

```python
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
```

Logs include timestamps, log levels, and detailed messages for debugging and monitoring purposes.

---

This API provides a robust solution for analyzing Douyin content, integrating seamlessly with Google services and external APIs. It is designed for scalability and reliability, with comprehensive error handling and logging.