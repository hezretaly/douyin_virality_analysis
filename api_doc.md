# Douyin Virality Analysis API Documentation

This document provides an overview of the **Douyin Virality Analysis API**, a FastAPI-based application for discovering, analyzing, and downloading viral videos from Douyin. It includes setup instructions, endpoint details, and concise API usage examples. For a detailed code explanation, refer to the accompanying code documentation.

## Table of Contents
1. [Overview](#overview)
2. [Setup and Authentication](#setup-and-authentication)
3. [API Endpoints](#api-endpoints)
   - [Discover and Save Creators](#discover-and-save-creators)
   - [Update Follower Counts](#update-follower-counts)
   - [Analyze and Generate Report](#analyze-and-generate-report)
   - [Download Videos to Drive](#download-videos-to-drive)

## Overview

The API provides four endpoints to:
1. Discover top creators based on virality velocity and save them to Google Sheets.
2. Update follower counts for creators in a Google Sheet.
3. Analyze recent videos and generate a virality report in a new Google Sheet.
4. Download videos and upload them to a timestamped Google Drive folder.

Built with **FastAPI**, it integrates with Google Drive, Google Sheets, Apify, and RapidAPI for Douyin data.

## Setup and Authentication

### Prerequisites
- Python 3.8+
- Install dependencies: `pip install fastapi pydantic httpx gspread google-api-python-client python-dotenv`
- Set up environment variables in a `.env` file:

```plaintext
API_KEY_SECRET=your_api_key
GOOGLE_CREDENTIALS_PATH=/path/to/credentials.json
APIFY_TOKEN=your_apify_token
RAPIDAPI_KEY=your_rapidapi_key
```

### Authentication
All endpoints require an API key passed via the `x-api-key` header.

**Example**:

```http
POST /discover_and_save_creators HTTP/1.1
Host: your-api-host
x-api-key: your_api_key
Content-Type: application/json
```

### Running the API
Run the FastAPI server using Uvicorn:

```bash
uvicorn main:app --host 0.0.0.0 --port 8000
```

Access the interactive API documentation at `http://your-api-host:8000/docs`.

## API Endpoints

### Discover and Save Creators

**Endpoint**: `POST /discover_and_save_creators`

**Description**: Scrapes videos using Apify, calculates virality velocity, identifies top creators, and saves new creators to a Google Sheet.

**Request**:
- **Body** (JSON):

```json
{
  "search_terms": ["dance", "music"],
  "spreadsheet_id": "your_spreadsheet_id",
  "sheet_name": "Creators",
  "max_videos_per_term": 100,
  "top_creators_to_rank": 20
}
```

- **Headers**:
  - `x-api-key: your_api_key`

**Response** (JSON):

```json
{
  "message": "Process complete. Identified 20 top creators.",
  "new_creators_added": 5,
  "top_ranked_sec_uids": ["secUid1", "secUid2", ...]
}
```

**Example**:

```bash
curl -X POST "http://your-api-host:8000/discover_and_save_creators" \
-H "x-api-key: your_api_key" \
-H "Content-Type: application/json" \
-d '{"search_terms": ["dance"], "spreadsheet_id": "your_spreadsheet_id", "sheet_name": "Creators", "max_videos_per_term": 100, "top_creators_to_rank": 20}'
```

**Errors**:
- `401`: Invalid or missing API key.
- `500`: Server errors (e.g., Apify or Google Sheets issues).

### Update Follower Counts

**Endpoint**: `POST /update_follower_counts`

**Description**: Updates missing follower counts in a Google Sheet using RapidAPI.

**Request**:
- **Body** (JSON):

```json
{
  "spreadsheet_id": "your_spreadsheet_id",
  "sheet_name": "Creators"
}
```

- **Headers**:
  - `x-api-key: your_api_key`

**Response** (JSON):

```json
{
  "message": "Follower count update process complete.",
  "users_checked": 50,
  "users_updated": 10,
  "users_failed": 2
}
```

**Example**:

```bash
curl -X POST "http://your-api-host:8000/update_follower_counts" \
-H "x-api-key: your_api_key" \
-H "Content-Type: application/json" \
-d '{"spreadsheet_id": "your_spreadsheet_id", "sheet_name": "Creators"}'
```

**Errors**:
- `404`: Spreadsheet or sheet not found.
- `500`: Server errors (e.g., RapidAPI or Google Sheets issues).

### Analyze and Generate Report

**Endpoint**: `POST /analyze_and_generate_report`

**Description**: Analyzes recent videos for up to 20 creators, calculates virality scores, and saves a report to a new Google Sheet.

**Request**:
- **Body** (JSON):

```json
{
  "spreadsheet_id": "your_spreadsheet_id",
  "sheet_name": "Creators"
}
```

- **Headers**:
  - `x-api-key: your_api_key`

**Response** (JSON):

```json
{
  "message": "Successfully generated video virality report.",
  "videos_processed": 150,
  "report_sheet_url": "https://docs.google.com/spreadsheets/d/your_spreadsheet_id/edit#gid=123456"
}
```

**Example**:

```bash
curl -X POST "http://your-api-host:8000/analyze_and_generate_report" \
-H "x-api-key: your_api_key" \
-H "Content-Type: application/json" \
-d '{"spreadsheet_id": "your_spreadsheet_id", "sheet_name": "Creators"}'
```

**Errors**:
- `404`: Spreadsheet, sheet, or no user data found.
- `500`: Server errors (e.g., RapidAPI or Google Sheets issues).

### Download Videos to Drive

**Endpoint**: `POST /download_videos_to_drive`

**Description**: Downloads specified videos and uploads them to a new timestamped Google Drive folder.

**Request**:
- **Body** (JSON):

```json
{
  "parent_folder_id": "your_folder_id",
  "video_ids": ["video_id1", "video_id2"]
}
```

- **Headers**:
  - `x-api-key: your_api_key`

**Response** (JSON):

```json
{
  "message": "Video download process complete.",
  "new_folder_url": "https://drive.google.com/drive/folders/your_folder_id",
  "download_results": [
    {"video_id": "video_id1", "status": "success", "drive_link": "https://drive.google.com/file/d/file_id"},
    {"video_id": "video_id2", "status": "failed", "error_detail": "Download link not found"}
  ]
}
```

**Example**:

```bash
curl -X POST "http://your-api-host:8000/download_videos_to_drive" \
-H "x-api-key: your_api_key" \
-H "Content-Type: application/json" \
-d '{"parent_folder_id": "your_folder_id", "video_ids": ["video_id1", "video_id2"]}'
```

**Errors**:
- `400`: Empty video ID list.
- `500`: Server errors (e.g., Google Drive or RapidAPI issues).

---

This documentation provides a concise guide to using the Douyin Virality Analysis API. For detailed code explanations, refer to the accompanying code documentation.