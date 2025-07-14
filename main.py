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

# Google API Imports
from google.oauth2.service_account import Credentials
from googleapiclient.discovery import build
from googleapiclient.http import MediaInMemoryUpload
from googleapiclient.errors import HttpError as GoogleHttpError
import gspread


load_dotenv()
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')

app = FastAPI(
    title="Douyin Virality Analysis API",
    description="A four-step API to discover, analyze, and download top viral videos.",
    version="3.0.0"
)

API_KEY = os.getenv("API_KEY_SECRET")
API_KEY_NAME = "x-api-key"
api_key_header = APIKeyHeader(name=API_KEY_NAME, auto_error=True)

async def get_api_key(api_key_header: str = Security(api_key_header)):
    """Validates the API key from the request header."""
    if not API_KEY:
        raise HTTPException(status_code=500, detail="API_KEY_SECRET is not configured on the server.")
    if api_key_header == API_KEY:
        return api_key_header
    raise HTTPException(status_code=401, detail="Invalid or missing API Key.")

# --- Google Drive Service Initialization ---
def get_drive_service():
    """Builds and returns an authenticated Google Drive API service object."""
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

# --- Google Drive Folder Creation (Corrected with Shared Drive support) ---
def create_drive_folder(service, folder_name: str, parent_folder_id: str) -> Dict[str, str]:
    """Creates a new folder inside a specified parent folder with Shared Drive support."""
    file_metadata = {
        'name': folder_name,
        'parents': [parent_folder_id],
        'mimeType': 'application/vnd.google-apps.folder'
    }
    try:
        folder = service.files().create(
            body=file_metadata,
            fields='id, webViewLink',
            supportsAllDrives=True  
        ).execute()
        logging.info(f"[Drive] Created folder '{folder_name}' with ID: {folder.get('id')}")
        return {"id": folder.get('id'), "link": folder.get('webViewLink')}
    except GoogleHttpError as error:
        logging.error(f"[Drive] FOLDER CREATION FAILED for '{folder_name}'. Reason: {error}")
        raise HTTPException(status_code=error.resp.status, detail=f"Failed to create Google Drive folder: {error}")

# --- Google Drive File Upload (Corrected with Shared Drive support) ---
def upload_data_to_drive(service, data: bytes, filename: str, folder_id: str, mimetype: str) -> str:
    """Uploads in-memory data to a specific folder in Google Drive with Shared Drive support."""
    try:
        media = MediaInMemoryUpload(data, mimetype=mimetype, resumable=True)
        file_metadata = {'name': filename, 'parents': [folder_id]}
        file = service.files().create(
            body=file_metadata,
            media_body=media,
            fields='id, webViewLink',
            supportsAllDrives=True
        ).execute()
        success_link = file.get('webViewLink')
        logging.info(f"Successfully uploaded '{filename}'. Drive link: {success_link}")
        return success_link
    except GoogleHttpError as error:
        logging.error(f"Google Drive upload failed for file '{filename}'. Reason: {error}")
        raise Exception(f"An error occurred during Google Drive upload: {error}")

def get_gspread_client():
    """Builds and returns a gspread client object."""
    try:
        credentials_path = os.getenv("GOOGLE_CREDENTIALS_PATH")
        if not credentials_path or not os.path.exists(credentials_path):
            raise FileNotFoundError("Google credentials file not found.")
        return gspread.service_account(filename=credentials_path)
    except Exception as e:
        logging.error(f"[Gspread Init] Failed to build client: {e}")
        raise HTTPException(status_code=500, detail="Could not initialize Google Sheets client.")

# --- Pydantic Models for the Request and Response ---

class DiscoverAndSaveRequest(BaseModel):
    search_terms: List[str] = Field(..., description="List of keywords to search for videos.")
    spreadsheet_id: str = Field(..., description="The unique ID of the target Google Spreadsheet.")
    sheet_name: str = Field(..., description="The name of the worksheet to save creator data to.")
    max_videos_per_term: int = Field(100, description="Max videos to scrape per search term.")
    top_creators_to_rank: int = Field(20, description="The number of top creators to identify and save.")

class DiscoverAndSaveResponse(BaseModel):
    message: str
    new_creators_added: int
    top_ranked_sec_uids: List[str] = Field(..., description="The ranked list of secUids identified in this run.")

# --- Corrected API Endpoint ---

@app.post("/discover_and_save_creators", response_model=DiscoverAndSaveResponse)
async def discover_and_save_creators(request: DiscoverAndSaveRequest):
    """
    Phase 1: Discovers top creators by Virality Velocity, then saves any new creators
    to the specified Google Sheet, avoiding duplicates.
    """
    APIFY_API_URL = "https://api.apify.com/v2/acts/natanielsantos~douyin-scraper/run-sync-get-dataset-items"
    apify_token = os.getenv("APIFY_TOKEN")
    if not apify_token:
        raise HTTPException(status_code=500, detail="APIFY_TOKEN not configured.")

    # Step 1: Discover Videos via Apify
    async with httpx.AsyncClient(timeout=300.0) as client:
        logging.info(f"Starting Apify scrape for terms: {request.search_terms}")
        api_params = {"token": apify_token}
        api_payload = {
            "searchTermsOrHashtags": request.search_terms,
            "maxItemsPerUrl": request.max_videos_per_term
        }
        
        try:
            response = await client.post(APIFY_API_URL, params=api_params, json=api_payload)
            response.raise_for_status()  # This will raise an exception for 4xx or 5xx status codes
            scraped_data = response.json()
        except httpx.HTTPStatusError as e:
            # Provide a more detailed error message if the API call fails
            logging.error(f"Apify API request failed with status {e.response.status_code}: {e.response.text}")
            raise HTTPException(
                status_code=502, # Bad Gateway: indicates an issue with an upstream server
                detail=f"Failed to fetch data from Apify API. Status: {e.response.status_code}. Please check your token and Apify account status."
            )
        except Exception as e:
            logging.error(f"An unexpected error occurred during Apify request: {e}")
            raise HTTPException(status_code=500, detail="An unexpected server error occurred.")

    # Step 2: Calculate Virality Velocity for all videos
    logging.info(f"Calculating Virality Velocity for {len(scraped_data)} videos...")
    video_velocities = []
    current_time_ts = int(datetime.now(timezone.utc).timestamp())

    for video in scraped_data:
        stats = video.get('statistics', {})
        create_time = video.get('createTime', current_time_ts)
        video_age_in_hours = max(1, (current_time_ts - create_time) / 3600)
        
        weighted_engagement = (
            stats.get('diggCount', 0) * 0.5 +
            stats.get('commentCount', 0) * 1.5 +
            stats.get('shareCount', 0) * 2.0 +
            stats.get('collectCount', 0) * 1.0
        )
        virality_velocity = weighted_engagement / video_age_in_hours
        
        video_velocities.append({
            "authorMeta": video.get('authorMeta', {}),
            "velocity": virality_velocity
        })

    # Step 3: Identify Top Creators from the most viral videos
    video_velocities.sort(key=lambda v: v['velocity'], reverse=True)
    top_creators_data = []
    seen_uids = set()
    for video in video_velocities:
        author_meta = video.get('authorMeta', {})
        secUid = author_meta.get('secUid')
        if secUid and secUid not in seen_uids:
            top_creators_data.append(author_meta)
            seen_uids.add(secUid)
            if len(top_creators_data) >= request.top_creators_to_rank:
                break
    
    # Step 4: Connect to Google Sheets and update with new creators
    try:
        gc = get_gspread_client()
        spreadsheet = gc.open_by_key(request.spreadsheet_id)

        try:
            worksheet = spreadsheet.worksheet(request.sheet_name)
            logging.info(f"Found existing sheet named '{request.sheet_name}'.")
        except gspread.exceptions.WorksheetNotFound:
            logging.info(f"Sheet '{request.sheet_name}' not found. Creating it...")
            headers = ['Creator Name', 'Creator SecUid', 'Account Link', 'Follower Count']
            worksheet = spreadsheet.add_worksheet(title=request.sheet_name, rows=1, cols=len(headers))
            worksheet.append_row(headers)
            logging.info(f"Sheet '{request.sheet_name}' created with headers.")

        existing_records = worksheet.get_all_records()
        existing_secuids = {str(row.get('Creator SecUid')) for row in existing_records}
        logging.info(f"Found {len(existing_secuids)} existing creators in the sheet.")

        rows_to_append = []
        for creator in top_creators_data:
            secUid = str(creator.get('secUid'))
            if secUid not in existing_secuids:
                account_link = f"https://www.douyin.com/user/{secUid}"
                new_row = [creator.get('name'), secUid, account_link, '']
                rows_to_append.append(new_row)
                existing_secuids.add(secUid) # Add to set to prevent duplicates within the same run
                logging.info(f"New creator '{creator.get('name')}' is queued for insertion.")
            else:
                logging.info(f"Creator with SecUid '{secUid}' already exists. Skipping.")

        if rows_to_append:
            worksheet.append_rows(rows_to_append, value_input_option='USER_ENTERED')
            logging.info(f"Successfully appended {len(rows_to_append)} new rows to '{request.sheet_name}'.")
        else:
            logging.info("No new creators to append.")

    except gspread.exceptions.APIError as e:
        logging.error(f"A Google Sheets API error occurred: {e}")
        raise HTTPException(status_code=500, detail="An error occurred while interacting with Google Sheets.")
    except Exception as e:
        logging.error(f"An unexpected error occurred during the Sheets operation: {e}")
        raise HTTPException(status_code=500, detail="An unexpected server error occurred.")

    # The response should contain the ranked list of SecUids found in this run
    ranked_uids_for_response = [creator.get('secUid') for creator in top_creators_data]

    return DiscoverAndSaveResponse(
        message=f"Process complete. Identified {len(top_creators_data)} top creators.",
        new_creators_added=len(rows_to_append),
        top_ranked_sec_uids=ranked_uids_for_response
    )


class UpdateFollowersRequest(BaseModel):
    spreadsheet_id: str = Field(..., description="The unique ID of the target Google Spreadsheet.")
    sheet_name: str = Field(..., description="The name of the worksheet containing the creator data.")

class UpdateFollowersResponse(BaseModel):
    message: str
    users_checked: int
    users_updated: int
    users_failed: int

# --- API Endpoint ---

@app.post("/update_follower_counts", response_model=UpdateFollowersResponse)
async def update_follower_counts(request: UpdateFollowersRequest):
    """
    Scans a Google Sheet for creators missing a follower count, fetches the count
    using their secUid, and updates the sheet.
    """
    USER_DETAIL_URL = "https://douyin-media-no-watermark1.p.rapidapi.com/v1/social/douyin/web/user/detail"
    douyin_media_headers = {
        "x-rapidapi-key": os.getenv("RAPIDAPI_KEY"),
        "x-rapidapi-host": "douyin-media-no-watermark1.p.rapidapi.com",
        "content-type": "application/json"
    }

    # Step 1: Read all data from the specified Google Sheet
    try:
        gc = get_gspread_client()
        spreadsheet = gc.open_by_key(request.spreadsheet_id)
        worksheet = spreadsheet.worksheet(request.sheet_name)
        all_rows = worksheet.get_all_values() # Get as a list of lists to preserve row numbers
    except gspread.exceptions.SpreadsheetNotFound:
        raise HTTPException(status_code=404, detail=f"Spreadsheet with ID '{request.spreadsheet_id}' not found.")
    except gspread.exceptions.WorksheetNotFound:
        raise HTTPException(status_code=404, detail=f"Sheet '{request.sheet_name}' not found in the spreadsheet.")
    except Exception as e:
        logging.error(f"Failed to read from Google Sheet: {e}")
        raise HTTPException(status_code=500, detail="An error occurred while accessing the Google Sheet.")

    if not all_rows or len(all_rows) < 2:
        return UpdateFollowersResponse(message="Sheet is empty or contains only headers.", users_checked=0, users_updated=0, users_failed=0)

    # Step 2: Identify creators who need their follower count updated
    headers = all_rows[0]
    try:
        secuid_col_index = headers.index('Creator SecUid')
        follower_col_index = headers.index('Follower Count')
    except ValueError as e:
        raise HTTPException(status_code=400, detail=f"Missing required column in sheet: {e}. Please ensure 'Creator SecUid' and 'Follower Count' columns exist.")

    creators_to_update = []
    for i, row in enumerate(all_rows[1:], start=2): # Start from row 2
        # Check if the row has enough columns and if the follower count is empty
        if len(row) > follower_col_index and not row[follower_col_index].strip():
            sec_uid = row[secuid_col_index]
            if sec_uid:
                creators_to_update.append({"row_num": i, "sec_uid": sec_uid})

    if not creators_to_update:
        return UpdateFollowersResponse(message="No users needed a follower count update.", users_checked=len(all_rows) - 1, users_updated=0, users_failed=0)

    logging.info(f"Found {len(creators_to_update)} users to update with follower counts.")

    # Step 3: Fetch follower counts for the identified creators
    users_failed = 0
    updates_to_batch = []

    async with httpx.AsyncClient() as client:
        for creator in creators_to_update:
            sec_id = creator["sec_uid"]
            payload = {"sec_user_id": sec_id}
            try:
                response = await client.post(USER_DETAIL_URL, json=payload, headers=douyin_media_headers, timeout=30)
                if response.status_code == 200:
                    user_data = response.json().get("user", {})
                    follower_count = user_data.get("follower_count")
                    if follower_count is not None:
                        # Prepare the update for batch operation
                        cell_to_update = gspread.cell.Cell(row=creator["row_num"], col=follower_col_index + 1, value=follower_count)
                        updates_to_batch.append(cell_to_update)
                        logging.info(f"Successfully fetched follower count for {sec_id}: {follower_count}")
                    else:
                        users_failed += 1
                        logging.warning(f"API response for {sec_id} did not contain a follower count.")
                else:
                    users_failed += 1
                    logging.error(f"Failed to fetch data for {sec_id}. Status: {response.status_code}, Response: {response.text}")
            except Exception as e:
                users_failed += 1
                logging.error(f"An exception occurred while fetching data for {sec_id}: {e}")

    # Step 4: Batch update the Google Sheet with the new follower counts
    if updates_to_batch:
        try:
            worksheet.update_cells(updates_to_batch, value_input_option='USER_ENTERED')
            logging.info(f"Successfully updated {len(updates_to_batch)} users in the spreadsheet.")
        except Exception as e:
            logging.error(f"Failed to batch update Google Sheet: {e}")
            # The updates failed, so we consider all attempted updates as failed.
            users_failed += len(updates_to_batch)

    return UpdateFollowersResponse(
        message="Follower count update process complete.",
        users_checked=len(all_rows) - 1,
        users_updated=len(updates_to_batch),
        users_failed=users_failed
    )



class AnalyzeAndReportRequest(BaseModel):
    spreadsheet_id: str = Field(..., description="The unique ID of the source Google Spreadsheet.")
    sheet_name: str = Field(..., description="The name of the sheet containing the user list.")

class AnalyzeAndReportResponse(BaseModel):
    message: str
    videos_processed: int
    report_sheet_url: str

# --- API Endpoint ---

@app.post("/analyze_and_generate_report", response_model=AnalyzeAndReportResponse)
async def analyze_and_generate_report(request: AnalyzeAndReportRequest):
    """
    Fetches recent videos for users from a sheet, calculates a detailed
    virality score, and saves a sorted report to a new sheet.
    """
    # --- Configuration ---
    MAX_USERS_TO_PROCESS = 20
    VIDEOS_PER_USER = 10
    W1 = 0.4  # Weight for Virality Velocity
    W2 = 0.6  # Weight for Engagement-to-Follower Ratio
    RECENT_VIDEOS_URL = "https://douyin-media-no-watermark1.p.rapidapi.com/v1/social/douyin/web/aweme/post"
    douyin_media_headers = {"x-rapidapi-key": os.getenv("RAPIDAPI_KEY"), "x-rapidapi-host": "douyin-media-no-watermark1.p.rapidapi.com"}

    # Step 1: Read creator data from the source Google Sheet
    try:
        gc = get_gspread_client()
        spreadsheet = gc.open_by_key(request.spreadsheet_id)
        worksheet = spreadsheet.worksheet(request.sheet_name)
        # Use get_all_records to work with dictionaries, which is more robust
        all_users = worksheet.get_all_records()
    except gspread.exceptions.SpreadsheetNotFound:
        raise HTTPException(status_code=404, detail=f"Spreadsheet with ID '{request.spreadsheet_id}' not found.")
    except gspread.exceptions.WorksheetNotFound:
        raise HTTPException(status_code=404, detail=f"Sheet '{request.sheet_name}' not found.")
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"An error occurred while accessing the Google Sheet: {e}")

    if not all_users:
        raise HTTPException(status_code=404, detail="The source sheet contains no user data.")

    # Step 2: Select the last N users to process
    users_to_process = all_users[-MAX_USERS_TO_PROCESS:]
    logging.info(f"Selected the last {len(users_to_process)} users for analysis.")

    # Step 3: Fetch videos and calculate virality for each user
    all_video_reports = []
    current_time_ts = int(datetime.now(timezone.utc).timestamp())

    async with httpx.AsyncClient(timeout=300.0) as client:
        for user in users_to_process:
            sec_uid = user.get('Creator SecUid')
            follower_count = int(user.get('Follower Count', 0))

            if not sec_uid or not follower_count > 0:
                logging.warning(f"Skipping user '{user.get('Creator Name')}' due to missing SecUid or follower count.")
                continue

            logging.info(f"Processing user: {user.get('Creator Name')} ({sec_uid})")
            payload = {"sec_user_id": sec_uid, "count": VIDEOS_PER_USER, "max_cursor": "0"}
            
            try:
                response = await client.post(RECENT_VIDEOS_URL, json=payload, headers=douyin_media_headers)
                response.raise_for_status()
                videos = response.json().get('aweme_list', [])

                for video in videos:
                    stats = video.get('statistics', {})
                    digg_count = stats.get('digg_count', 0)
                    comment_count = stats.get('comment_count', 0)
                    share_count = stats.get('share_count', 0)
                    collect_count = stats.get('collect_count', 0)
                    recommend_count = stats.get('recommend_count', 0)
                    create_time = video.get('create_time', current_time_ts)
                    video_id = video.get('aweme_id')

                    # --- Virality Score Calculation ---
                    # 1. Virality Velocity (from phase 1 logic)
                    video_age_in_hours = max(1, (current_time_ts - create_time) / 3600)
                    weighted_engagement = (digg_count * 0.5) + (comment_count * 1.5) + (share_count * 2.0) + (collect_count * 1.0)
                    virality_velocity = weighted_engagement / video_age_in_hours

                    # 2. Detailed Engagement & Ratio
                    detailed_engagement_score = (digg_count * 0.3) + (comment_count * 1.8) + (share_count * 2.5) + (collect_count * 1.2) + (recommend_count * 3.0)
                    engagement_to_follower_ratio = detailed_engagement_score / math.log(follower_count + 1)
                    
                    # 3. Final Weighted Score
                    final_virality_score = (W1 * virality_velocity) + (W2 * engagement_to_follower_ratio)
                    
                    # --- Prepare data for the report row ---
                    report_row = {
                        "Creator Name": user.get('Creator Name'),
                        "Creator SecUid": sec_uid,
                        "Account Link": user.get('Account Link'),
                        "Follower Count": follower_count,
                        "Video ID": video_id,
                        "Video URL": f"https://www.douyin.com/video/{video_id}",
                        "Description": video.get('desc'),
                        "Create Timestamp": create_time,
                        "Create Date": datetime.fromtimestamp(create_time, tz=timezone.utc).strftime('%Y-%m-%d'),
                        "Likes": digg_count,
                        "Comments": comment_count,
                        "Shares": share_count,
                        "Bookmarks": collect_count,
                        "Recommendations": recommend_count,
                        "Virality Score": round(final_virality_score, 4)
                    }
                    all_video_reports.append(report_row)
            except Exception as e:
                logging.error(f"Failed to process videos for user {sec_uid}: {e}")

    if not all_video_reports:
        raise HTTPException(status_code=404, detail="Could not fetch or process any videos for the selected users.")

    # Step 4: Sort the final report by Virality Score
    all_video_reports.sort(key=lambda x: x['Virality Score'], reverse=True)

    # Step 5: Create a new sheet and save the report
    try:
        report_sheet_title = f"VideoReport_{datetime.now().strftime('%Y%m%d_%H%M%S')}"
        report_worksheet = spreadsheet.add_worksheet(title=report_sheet_title, rows=len(all_video_reports) + 1, cols=len(all_video_reports[0]))
        
        headers = list(all_video_reports[0].keys())
        sheet_rows = [list(row.values()) for row in all_video_reports]
        
        report_worksheet.update('A1', [headers])
        report_worksheet.update('A2', sheet_rows)

        report_sheet_url = f"https://docs.google.com/spreadsheets/d/{request.spreadsheet_id}/edit#gid={report_worksheet.id}"
        logging.info(f"Successfully created report sheet: {report_sheet_url}")
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to write the report to Google Sheets: {e}")

    return AnalyzeAndReportResponse(
        message="Successfully generated video virality report.",
        videos_processed=len(all_video_reports),
        report_sheet_url=report_sheet_url
    )


class DownloadRequest(BaseModel):
    parent_folder_id: str = Field(..., description="The ID of the parent folder in Google Drive where the new folder will be created. Must be in a Shared Drive.")
    video_ids: List[str] = Field(..., description="A list of Douyin video IDs (aweme_id) to download.")

class DownloadResult(BaseModel):
    video_id: str
    status: str
    drive_link: Optional[str] = None
    error_detail: Optional[str] = None

class DownloadResponse(BaseModel):
    message: str
    new_folder_url: str
    download_results: List[DownloadResult]

# --- API Endpoint ---

@app.post("/download_videos_to_drive", response_model=DownloadResponse)
async def download_videos_to_drive(request: DownloadRequest):
    """
    Downloads a list of videos by their IDs and uploads them to a new,
    timestamped folder in a specified Google Drive location.
    """
    if not request.video_ids:
        raise HTTPException(status_code=400, detail="The 'video_ids' list cannot be empty.")

    # --- Configuration ---
    VIDEO_DETAIL_URL = "https://douyin-media-no-watermark1.p.rapidapi.com/v1/social/douyin/web/aweme/detail"
    douyin_media_headers = {"x-rapidapi-key": os.getenv("RAPIDAPI_KEY"), "x-rapidapi-host": "douyin-media-no-watermark1.p.rapidapi.com"}

    # Step 1: Create a new timestamped folder in Google Drive
    try:
        drive_service = get_drive_service()
        folder_name = f"Downloaded_Videos_{datetime.now().strftime('%Y%m%d_%H%M%S')}"
        
        logging.info(f"Creating new Drive folder '{folder_name}' inside parent '{request.parent_folder_id}'")
        new_folder_info = create_drive_folder(drive_service, folder_name, request.parent_folder_id)
        new_folder_id = new_folder_info["id"]
        new_folder_url = new_folder_info["link"]
    except HTTPException as e:
        raise e
    except Exception as e:
        logging.error(f"Failed to create Google Drive folder: {e}")
        raise HTTPException(status_code=500, detail=f"Failed to create Google Drive folder: {e}")

    # Step 2: Loop through video IDs, download, and upload to the new folder
    download_results = []
    async with httpx.AsyncClient(timeout=300.0) as client:
        for video_id in request.video_ids:
            try:
                # Get the direct, no-watermark download link for the video
                detail_payload = {"id": video_id}
                logging.info(f"Fetching download details for video ID: {video_id}")
                detail_response = await client.post(VIDEO_DETAIL_URL, json=detail_payload, headers=douyin_media_headers, timeout=45.0)
                detail_response.raise_for_status()
                detail_data = detail_response.json().get('aweme_detail', {})

                if not detail_data or 'video' not in detail_data or not detail_data['video']['play_addr']['url_list']:
                    raise ValueError("Download link not found in the API response.")
                
                downloadable_url = detail_data['video']['play_addr']['url_list'][0]

                # Download the video content
                logging.info(f"Downloading video content from URL for ID: {video_id}")
                video_content_response = await client.get(downloadable_url, timeout=120.0)
                video_content_response.raise_for_status()
                video_content = video_content_response.content
                
                # Upload the content to Google Drive
                video_name = f"douyin_{video_id}.mp4"
                drive_link = upload_data_to_drive(drive_service, video_content, video_name, new_folder_id, 'video/mp4')
                
                download_results.append(DownloadResult(video_id=video_id, status="success", drive_link=drive_link))
                logging.info(f"Successfully downloaded and uploaded video ID: {video_id}")

            except Exception as e:
                error_message = f"Failed to process video {video_id}: {e}"
                logging.error(error_message)
                download_results.append(DownloadResult(video_id=video_id, status="failed", error_detail=str(e)))
    
    return DownloadResponse(
        message="Video download process complete.",
        new_folder_url=new_folder_url,
        download_results=download_results
    )