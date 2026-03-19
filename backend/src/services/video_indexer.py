"""
Connector between the app and Azure Video Indexer.
"""

import logging
import os
import re
import time

import requests
import yt_dlp
from azure.identity import DefaultAzureCredential

logger = logging.getLogger("video-indexer")


class VideoIndexerService:
    def __init__(self):
        self.account_id = os.getenv("AZURE_VI_ACCOUNT_ID")
        self.location = os.getenv("AZURE_VI_LOCATION")
        self.subscription_id = os.getenv("AZURE_SUBSCRIPTION_ID")
        self.resource_group = os.getenv("AZURE_RESOURCE_GROUP")
        self.vi_name = os.getenv("AZURE_VI_NAME", "project-brand-guardian-001")
        self.credential = DefaultAzureCredential()
        self._account_access_token = None
        self._validate_config()

    def _validate_config(self):
        required = {
            "AZURE_VI_ACCOUNT_ID": self.account_id,
            "AZURE_VI_LOCATION": self.location,
            "AZURE_SUBSCRIPTION_ID": self.subscription_id,
            "AZURE_RESOURCE_GROUP": self.resource_group,
            "AZURE_VI_NAME": self.vi_name,
        }
        missing = [name for name, value in required.items() if not value]
        if missing:
            raise RuntimeError(
                f"Missing Azure Video Indexer configuration: {', '.join(missing)}"
            )

    def get_access_token(self):
        """Generate an ARM access token."""
        try:
            token_object = self.credential.get_token(
                "https://management.azure.com/.default"
            )
            return token_object.token
        except Exception as exc:
            logger.error("Failed to get Azure Token: %s", exc)
            raise

    def get_account_token(self, arm_access_token):
        """Exchange an ARM token for an Azure Video Indexer account token."""
        url = (
            f"https://management.azure.com/subscriptions/{self.subscription_id}"
            f"/resourceGroups/{self.resource_group}"
            f"/providers/Microsoft.VideoIndexer/accounts/{self.vi_name}"
            f"/generateAccessToken?api-version=2024-01-01"
        )
        headers = {"Authorization": f"Bearer {arm_access_token}"}
        payload = {"permissionType": "Contributor", "scope": "Account"}
        response = requests.post(url, headers=headers, json=payload, timeout=60)
        if response.status_code != 200:
            raise Exception(f"Failed to get VI Account Token: {response.text}")

        access_token = response.json().get("accessToken")
        if not access_token:
            raise Exception("Video Indexer account token was not returned by Azure.")
        return access_token

    def get_cached_account_token(self, force_refresh=False):
        if force_refresh or not self._account_access_token:
            arm_token = self.get_access_token()
            self._account_access_token = self.get_account_token(arm_token)
        return self._account_access_token

    def download_youtube_video(self, url, output_path="temp_video.mp4"):
        """Download a YouTube video to a local file."""
        logger.info("Downloading YouTube video: %s", url)

        ydl_opts = {
            "format": "best[ext=mp4]/best",
            "outtmpl": output_path,
            "quiet": False,
            "overwrites": True,
            "extractor_args": {"youtube": {"player_client": ["android", "web"]}},
            "http_headers": {
                "User-Agent": (
                    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                    "AppleWebKit/537.36"
                )
            },
        }

        try:
            with yt_dlp.YoutubeDL(ydl_opts) as ydl:
                ydl.download([url])
            logger.info("Download complete.")
            return output_path
        except Exception as exc:
            raise Exception(f"YouTube video download failed: {exc}") from exc

    def upload_video(self, video_path, video_name):
        """Upload a local file to Azure Video Indexer."""
        vi_token = self.get_cached_account_token()
        api_url = f"https://api.videoindexer.ai/{self.location}/Accounts/{self.account_id}/Videos"

        params = {
            "accessToken": vi_token,
            "name": video_name,
            "privacy": "Private",
            "indexingPreset": "Default",
            "preventDuplicates": "false",
        }

        logger.info("Uploading file %s to Azure...", video_path)

        with open(video_path, "rb") as video_file:
            files = {"file": video_file}
            response = requests.post(
                api_url, params=params, files=files, timeout=300
            )

        if response.status_code != 200:
            try:
                error_payload = response.json()
            except ValueError:
                error_payload = {}

            if error_payload.get("ErrorType") in {
                "VIDEO_ALREADY_IN_PROGRESS",
                "ALREADY_EXISTS",
            }:
                match = re.search(
                    r"video id: '([^']+)'", error_payload.get("Message", "")
                )
                if match:
                    existing_video_id = match.group(1)
                    logger.warning(
                        "Video already exists in Azure Video Indexer. Reusing Azure video id %s.",
                        existing_video_id,
                    )
                    return existing_video_id

            raise Exception(f"Azure upload failed: {response.text}")

        video_id = response.json().get("id")
        if not video_id:
            raise Exception(
                f"Azure upload succeeded but no video id was returned: {response.text}"
            )
        return video_id

    def wait_for_processing(self, video_id, poll_interval_seconds=30, timeout_seconds=1800):
        """Poll Azure Video Indexer until processing completes."""
        logger.info("Waiting for video %s to process...", video_id)
        vi_token = self.get_cached_account_token()
        deadline = time.monotonic() + timeout_seconds

        while True:
            if time.monotonic() > deadline:
                raise TimeoutError(
                    f"Azure Video Indexer timed out after {timeout_seconds} seconds "
                    f"while processing video {video_id}."
                )

            url = (
                f"https://api.videoindexer.ai/{self.location}/Accounts/"
                f"{self.account_id}/Videos/{video_id}/Index"
            )
            params = {"accessToken": vi_token}
            response = requests.get(url, params=params, timeout=60)

            if response.status_code == 401:
                logger.info("Video Indexer token expired, refreshing token.")
                vi_token = self.get_cached_account_token(force_refresh=True)
                continue
            if response.status_code != 200:
                raise Exception(f"Failed to fetch Video Indexer status: {response.text}")

            data = response.json()
            state = data.get("state")
            if not state and data.get("videos"):
                state = data["videos"][0].get("state")

            if state == "Processed":
                return data
            if state == "Failed":
                raise Exception("Video Indexing failed in Azure.")
            if state == "Quarantined":
                raise Exception("Video quarantined due to policy or copyright rules.")

            logger.info("Status: %s... waiting %ss", state, poll_interval_seconds)
            time.sleep(poll_interval_seconds)

    def extract_data(self, vi_json):
        """Parse Azure Video Indexer JSON into the graph state shape."""
        transcript_lines = []
        for video in vi_json.get("videos", []):
            insights = video.get("insights") or video.get("insight") or {}
            for insight in insights.get("transcript", []):
                transcript_lines.append(insight.get("text"))

        ocr_lines = []
        for video in vi_json.get("videos", []):
            insights = video.get("insights") or video.get("insight") or {}
            for insight in insights.get("ocr", []):
                ocr_lines.append(insight.get("text"))

        duration = vi_json.get("summarizedInsights", {}).get("duration")
        if isinstance(duration, dict):
            duration = duration.get("seconds")

        return {
            "transcript": " ".join(filter(None, transcript_lines)).strip(),
            "ocr_text": ocr_lines,
            "video_metadata": {
                "duration": duration,
                "platform": "youtube",
            },
        }
