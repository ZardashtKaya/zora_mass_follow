import requests
import json
import time
import os
import random
import string  # Keep for clean_name
import math  # For batch calculation
import concurrent.futures
from urllib.parse import quote
import logging  # Use standard logging
import sys
import argparse  # For command-line arguments
from datetime import datetime

# --- Color Setup ---
try:
    import colorama

    colorama.init()
except ImportError:
    # colorama is optional
    pass

COLOR_RESET = "\033[0m"
COLOR_DEBUG = "\033[0;33m"  # Yellow/Orange
COLOR_INFO = "\033[0;32m"  # Green
COLOR_WARNING = "\033[1;33m"  # Bright Yellow
COLOR_ERROR = "\033[0;31m"  # Red
COLOR_CRITICAL = "\033[1;31m"  # Bright Red
COLOR_HANDLE = "\033[0;36m"  # Cyan
COLOR_SEPARATOR = "\033[0;34m"  # Blue
COLOR_RESPONSE = "\033[2;37m"  # Dim White/Grey


# --- Custom Log Formatter ---
class ColoredFormatter(logging.Formatter):
    LOG_FORMAT = "%(asctime)s - %(levelname)s - %(message)s"
    COLOR_MAP = {
        logging.DEBUG: COLOR_DEBUG,
        logging.INFO: COLOR_INFO,
        logging.WARNING: COLOR_WARNING,
        logging.ERROR: COLOR_ERROR,
        logging.CRITICAL: COLOR_CRITICAL,
    }

    def format(self, record):
        # Basic formatting first
        log_message = super().format(record)
        # Apply level color
        color = self.COLOR_MAP.get(record.levelno, COLOR_RESET)
        formatted_message = f"{color}{log_message}{COLOR_RESET}"

        # Enhance specific parts like handles if needed - simple approach
        # Note: This simple replacement might color unintended parts if quotes are used elsewhere.
        # A more robust solution might involve regex or modifying the logger record itself.
        # formatted_message = formatted_message.replace("'", f"'{COLOR_HANDLE}")
        # formatted_message = formatted_message.replace(f"{COLOR_HANDLE}'", f"'{COLOR_RESET}{color}")
        return formatted_message


# --- Configuration ---

AUTH_TOKEN = os.getenv(
    "ZORA_AUTH_TOKEN",
    "eY.........",
)
NAMES_FILE = "names.txt"  # File containing names, one per line
SEARCH_API_URL_TEMPLATE = (
    "https://zora.co/api/trpc/mobile.profiles.searchProfile?input={encoded_input}"
)
FOLLOW_API_URL = "https://api.zora.co/universal/graphql"
MAX_WORKERS = 1  # Adjust as needed for performance vs rate limiting
SLEEP_DURATION_FOLLOW = 3  # Increased sleep between follows for the same search term
SLEEP_DURATION_SEARCH_SUBMIT = (
    0.1  # Sleep between submitting search tasks within a batch
)
EXTRACT_PROFILE_ID_FIELD = True  # Set to True to use 'profileId', False for 'handle'
BATCH_SIZE = 30  # Process in batches

# --- GraphQL Follow Mutation ---
FOLLOW_QUERY_STRING = """
mutation useFollowsMutation_followMutation(
  $profileId: String!
) {
  follow(followeeId: $profileId) {
    __typename
    ...FollowButton_profile
    id
  }
}

fragment FollowButton_profile on IGraphQLProfile {
  __isIGraphQLProfile: __typename
  vcFollowingStatus
}
"""

# --- Helper Functions ---


def clean_name(name):
    """Removes non-ASCII alphabetic characters from a string."""
    cleaned = "".join(c for c in name if c.isalpha() and c.isascii())
    logging.debug(f"Cleaned '{name}' -> '{cleaned}'")
    return cleaned


def make_request(method, url, headers, payload=None, description="request"):
    """Makes an HTTP request, handles errors, returns response object or None."""
    logging.debug(f"Making {method} {description} to {url}")
    if payload:
        logging.debug(
            f"Payload keys: {list(payload.keys())}"
            if isinstance(payload, dict)
            else "Payload present"
        )
    try:
        if method.upper() == "POST":
            response = requests.post(url, headers=headers, json=payload, timeout=30)
        else:  # Default to GET
            response = requests.get(url, headers=headers, timeout=30)

        logging.debug(
            f"{description.capitalize()} response status: {response.status_code}"
        )

        # Log full body only at DEBUG level AND if it's NOT a search request
        if logging.getLogger().isEnabledFor(logging.DEBUG):
            is_search_request = description.startswith("search for")
            if not is_search_request:  # <-- Only log body if not a search request
                response_body_text = response.text
                logging.debug(f"{description.capitalize()} Response Body:")
                try:
                    parsed_json = response.json()
                    logging.debug(
                        f"\n{COLOR_RESPONSE}{json.dumps(parsed_json, indent=2)}{COLOR_RESET}"
                    )
                except json.JSONDecodeError:
                    logging.debug(
                        f"\n{COLOR_RESPONSE}{response_body_text}{COLOR_RESET}"
                    )
                logging.debug(
                    f"{COLOR_SEPARATOR}----------------------------------------{COLOR_RESET}"
                )
            # else: # Optional: Log that body logging was skipped for search
            #     logging.debug(f"Skipping response body logging for {description}.")

        response.raise_for_status()
        return response

    except requests.exceptions.Timeout:
        logging.error(f"{description.capitalize()} request timed out to {url}")
    except requests.exceptions.ConnectionError:
        logging.error(f"Connection error during {description} to {url}")
    except requests.exceptions.HTTPError as e:
        # Log specific HTTP errors, especially rate limits if possible
        status_code = e.response.status_code
        reason = e.response.reason
        log_level = logging.ERROR
        # Treat 429 Rate Limit as a warning, maybe implement backoff later
        if status_code == 429:
            log_level = logging.WARNING
            reason += " (Rate Limit)"

        logging.log(
            log_level, f"HTTP error during {description}: {status_code} {reason}"
        )
        # Log error response body at WARNING or ERROR level for better diagnosis
        try:
            error_body = e.response.text
            logging.log(
                log_level, f"Error Response Body: {error_body[:500]}..."
            )  # Log truncated body
        except Exception:
            pass

    except requests.exceptions.RequestException as e:
        logging.error(f"Error during {description} request: {e}")
    except Exception as e:
        logging.error(f"An unexpected error occurred during {description}: {e}")

    return None


def search_profiles(search_term, auth_token):
    """Searches for profiles based on the search term, returns list of identifiers or empty list."""
    logging.info(
        f"Searching profiles for term: '{COLOR_HANDLE}{search_term}{COLOR_RESET}'"
    )
    search_field = "profileId" if EXTRACT_PROFILE_ID_FIELD else "handle"
    profile_identifiers = []

    try:
        input_json_obj = {"json": {"text": search_term}}
        input_json_str = json.dumps(input_json_obj, separators=(",", ":"))
        encoded_input = quote(input_json_str)

        url = SEARCH_API_URL_TEMPLATE.format(encoded_input=encoded_input)
        headers = {
            "Authorization": f"Bearer {auth_token}",
            "Accept": "application/json",
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36",
        }

        # Note: Response body logging for search is suppressed in make_request at DEBUG level
        response = make_request(
            "GET", url, headers, description=f"search for '{search_term}'"
        )

        if response:
            data = response.json()
            profiles = (
                data.get("result", {})
                .get("data", {})
                .get("json", {})
                .get("profiles", [])
            )
            if profiles:
                profile_identifiers = [
                    p.get(search_field) for p in profiles if p.get(search_field)
                ]
                logging.info(
                    f"Found {len(profile_identifiers)} profile identifier(s) ({search_field}) for '{COLOR_HANDLE}{search_term}{COLOR_RESET}'."
                )
                logging.debug(f"Identifiers found: {profile_identifiers}")
            else:
                logging.info(
                    f"No profiles found in response for '{COLOR_HANDLE}{search_term}{COLOR_RESET}'."
                )

    except json.JSONDecodeError:
        logging.error(
            f"Failed to decode JSON response for search term '{search_term}'. Request might have failed or returned non-JSON."
        )
    except Exception as e:
        logging.error(
            f"An unexpected error occurred during search processing for '{search_term}': {e}"
        )

    return profile_identifiers


def follow_profile(profile_identifier, auth_token):
    """Follows a profile and logs a concise status. Returns True on API success/already following, False otherwise."""
    follow_id_to_use = (
        profile_identifier  # API expects profileId or handle here based on its logic
    )

    headers = {
        "Authorization": f"Bearer {auth_token}",
        "Content-Type": "application/json",
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36",
    }
    payload = {
        "query": FOLLOW_QUERY_STRING,
        "variables": {"profileId": follow_id_to_use},
    }

    response = make_request(
        "POST",
        FOLLOW_API_URL,
        headers,
        payload=payload,
        description=f"follow '{profile_identifier}'",
    )

    if response:
        try:
            data = response.json()
            errors = data.get("errors")
            api_data_field = data.get("data")  # Get the top-level 'data' field safely

            # --- Handle API Errors First ---
            if errors:
                first_error = errors[0]
                error_message = first_error.get("message", "Unknown API error")
                log_level = logging.ERROR  # Default log level for errors

                # Specific error handling
                if "Invalid user identifier" in error_message:
                    logging.warning(
                        f"Failed to follow '{COLOR_HANDLE}{profile_identifier}{COLOR_WARNING}': Invalid user identifier (API)."
                    )
                elif "already following" in error_message.lower():
                    # This isn't really an error for our script's goal
                    logging.info(
                        f"Already following '{COLOR_HANDLE}{profile_identifier}{COLOR_INFO}'. Considered success."
                    )
                    return True  # Treat 'already following' as success
                elif "Rate limit exceeded" in error_message:
                    # Log as warning, could implement backoff/retry later
                    logging.warning(
                        f"Rate limit hit trying to follow '{COLOR_HANDLE}{profile_identifier}{COLOR_WARNING}'. Message: {error_message}"
                    )
                    # Consider a short sleep here if rate limits are frequent
                    # time.sleep(1)
                else:
                    # Log other API errors
                    logging.error(
                        f"Failed to follow '{COLOR_HANDLE}{profile_identifier}{COLOR_ERROR}': API Error - {error_message}"
                    )
                return False  # API reported an error (excluding 'already following')

            # --- Handle Success Cases (No Errors) ---
            elif api_data_field and isinstance(api_data_field, dict):
                follow_result = api_data_field.get("follow")
                if follow_result and isinstance(follow_result, dict):
                    # Check for known success indicators
                    status = follow_result.get("vcFollowingStatus")
                    typename = follow_result.get("__typename")
                    # Accept known successful statuses/types
                    # Handle cases like `GraphQLAccountProfile` seen in logs
                    if status == "FOLLOWING" or typename in [
                        "GraphQLAccountProfile",
                        "IGraphQLFollowResult",
                    ]:
                        logging.info(
                            f"Successfully followed '{COLOR_HANDLE}{profile_identifier}{COLOR_INFO}' (Status: {status}, Type: {typename})."
                        )
                        return True
                    else:
                        # Data structure seems okay, but status/type unexpected
                        logging.warning(
                            f"Follow request for '{COLOR_HANDLE}{profile_identifier}{COLOR_WARNING}' completed, but status/type unexpected (Status: {status}, Type: {typename})."
                        )
                        logging.debug(
                            f"Unexpected follow response details: {json.dumps(follow_result, indent=2)}"
                        )
                        return False  # Treat as failure for consistency
                else:
                    # 'data' field existed, but no 'follow' key or it wasn't a dict
                    logging.warning(
                        f"Follow request for '{COLOR_HANDLE}{profile_identifier}{COLOR_WARNING}' completed, but 'follow' data missing or malformed in response."
                    )
                    logging.debug(
                        f"Malformed follow response data field: {api_data_field}"
                    )
                    return False  # Treat as failure
            else:
                # No 'errors' and no 'data' field or 'data' is null/not a dict
                logging.error(
                    f"Follow request for '{COLOR_HANDLE}{profile_identifier}{COLOR_ERROR}' completed, but response lacks expected 'data' field and has no 'errors'."
                )
                logging.debug(
                    f"Unexpected response structure: {json.dumps(data, indent=2)}"
                )
                return False  # Treat as failure

        except json.JSONDecodeError:
            logging.error(
                f"Failed to decode JSON response for follow request '{COLOR_HANDLE}{profile_identifier}{COLOR_ERROR}'."
            )
            return False
        except Exception as e:
            # Catch unexpected errors during the processing of the JSON response
            # This should prevent the 'NoneType' error if data structure is unexpected after error checks
            logging.error(
                f"Error processing follow response JSON for '{COLOR_HANDLE}{profile_identifier}{COLOR_ERROR}': {e}",
                exc_info=logging.getLogger().isEnabledFor(logging.DEBUG),
            )  # Show traceback if verbose
            return False
    else:
        # make_request already logged the HTTP/connection error
        logging.error(
            f"Follow request submission failed for '{COLOR_HANDLE}{profile_identifier}{COLOR_ERROR}' (Network/HTTP issue)."
        )
        return False  # Request itself failed


def process_search_term(search_term, auth_token, sleep_follow):
    """Worker function: searches for a term and follows results."""
    profile_identifiers = search_profiles(search_term, auth_token)
    followed_success_count = 0
    attempted_count = len(profile_identifiers)

    if profile_identifiers:
        logging.info(
            f"Starting follow process for {attempted_count} profile(s) found for search term '{COLOR_HANDLE}{search_term}{COLOR_RESET}'."
        )
        for i, identifier in enumerate(profile_identifiers):
            # Add a small delay *before* attempting follow, especially if rate limits occur
            # time.sleep(0.5) # Optional small delay before each follow attempt

            logging.info(
                f"--> Attempting follow {i+1}/{attempted_count} for ID/Handle: '{COLOR_HANDLE}{identifier}{COLOR_INFO}' (from search '{search_term}')"
            )
            if follow_profile(identifier, auth_token):
                followed_success_count += 1
            # else: # Optional: Add extra sleep if a follow attempt failed (e.g., rate limited)
            #     logging.warning(f"Follow failed for {identifier}, adding extra sleep...")
            #     time.sleep(sleep_follow * 2) # Double sleep after failure

            # Sleep between follow attempts for the *same* search term results
            if i < attempted_count - 1 and sleep_follow > 0:
                logging.debug(f"Sleeping for {sleep_follow}s before next follow...")
                time.sleep(sleep_follow)

        logging.info(
            f"Finished following for search term '{COLOR_HANDLE}{search_term}{COLOR_RESET}'. Success/Already Following: {followed_success_count}/{attempted_count}."
        )
    else:
        pass  # No action needed if no profiles found

    return search_term, followed_success_count, attempted_count


# --- Main Execution ---
if __name__ == "__main__":
    parser = argparse.ArgumentParser(
        description="Zora Profile Follower Script using names list and batches"
    )
    parser.add_argument(
        "-v",
        "--verbose",
        action="store_true",
        help="Enable verbose (DEBUG) logging output.",
    )
    args = parser.parse_args()

    # Configure Logging
    log_level = logging.DEBUG if args.verbose else logging.INFO
    root_logger = logging.getLogger()
    root_logger.setLevel(log_level)
    # Clear previous handlers
    for handler in root_logger.handlers[:]:
        root_logger.removeHandler(handler)
    # Setup new handler
    stream_handler = logging.StreamHandler(sys.stdout)
    stream_handler.setLevel(log_level)
    formatter = ColoredFormatter(ColoredFormatter.LOG_FORMAT)
    stream_handler.setFormatter(formatter)
    root_logger.addHandler(stream_handler)

    # --- Start Script ---
    print(f"{COLOR_SEPARATOR}========================================{COLOR_RESET}")
    logging.info("Starting Zora Profile Follower Script (from names list, batched)")
    print(f"{COLOR_SEPARATOR}========================================{COLOR_RESET}")

    if (
        not AUTH_TOKEN or AUTH_TOKEN == "YOUR_FRESH_BEARER_TOKEN_HERE"
    ):  # Check placeholder too
        logging.critical("Authentication token is missing or is the placeholder.")
        logging.critical(
            f"Please set the ZORA_AUTH_TOKEN environment variable or replace the placeholder in the script."
        )
        sys.exit(1)
    else:
        logging.info(f"Authentication token loaded (starts with: {AUTH_TOKEN[:8]}...).")

    logging.info(f"Log Level set to: {'DEBUG' if args.verbose else 'INFO'}")
    logging.info(f"Reading names from: {NAMES_FILE}")
    logging.info(f"Using up to {MAX_WORKERS} parallel workers.")
    logging.info(f"Processing in batches of size: {BATCH_SIZE}")
    logging.info(
        f"Follow sleep duration between profiles (same search): {SLEEP_DURATION_FOLLOW}s"
    )
    logging.info(
        f"Search task submission sleep (within batch): {SLEEP_DURATION_SEARCH_SUBMIT}s"
    )
    logging.info(
        f"Extracting field from search: {'profileId' if EXTRACT_PROFILE_ID_FIELD else 'handle'}"
    )

    processed_cleaned_names = set()
    total_tasks_submitted = 0
    total_profiles_found = 0
    total_successful_follows = 0
    skipped_duplicates = 0
    skipped_invalid = 0
    names_read_count = 0

    try:
        with open(NAMES_FILE, "r", encoding="utf-8") as f:
            raw_names = [line.strip() for line in f if line.strip()]
        names_read_count = len(raw_names)
        logging.info(
            f"Read {names_read_count} names from '{NAMES_FILE}'. Shuffling order for processing..."
        )
        random.shuffle(raw_names)

        with concurrent.futures.ThreadPoolExecutor(max_workers=MAX_WORKERS) as executor:
            num_batches = math.ceil(names_read_count / BATCH_SIZE)
            logging.info(
                f"Processing {names_read_count} names in {num_batches} batches of up to {BATCH_SIZE}."
            )

            for batch_num in range(num_batches):
                start_index = batch_num * BATCH_SIZE
                end_index = min((batch_num + 1) * BATCH_SIZE, names_read_count)
                current_batch_names = raw_names[start_index:end_index]
                batch_futures = []

                logging.info(
                    f"{COLOR_SEPARATOR}--- Starting Batch {batch_num + 1}/{num_batches} ({len(current_batch_names)} names) ---{COLOR_RESET}"
                )

                tasks_in_batch = 0
                for raw_name in current_batch_names:
                    cleaned_name = clean_name(raw_name)

                    if not cleaned_name:
                        logging.debug(
                            f"Skipping empty name after cleaning original '{raw_name}' in batch {batch_num + 1}."
                        )
                        skipped_invalid += 1
                        continue

                    if cleaned_name not in processed_cleaned_names:
                        processed_cleaned_names.add(cleaned_name)
                        logging.info(
                            f"Submitting task for cleaned name: '{COLOR_HANDLE}{cleaned_name}{COLOR_INFO}' (Original: '{raw_name}') [Batch {batch_num + 1}]"
                        )
                        future = executor.submit(
                            process_search_term,
                            cleaned_name,
                            AUTH_TOKEN,
                            SLEEP_DURATION_FOLLOW,
                        )
                        batch_futures.append(future)
                        total_tasks_submitted += 1
                        tasks_in_batch += 1
                        if SLEEP_DURATION_SEARCH_SUBMIT > 0:
                            time.sleep(SLEEP_DURATION_SEARCH_SUBMIT)
                    else:
                        logging.info(
                            f"Skipping duplicate cleaned name: '{COLOR_HANDLE}{cleaned_name}{COLOR_INFO}' (Original: '{raw_name}') [Batch {batch_num + 1}]"
                        )
                        skipped_duplicates += 1

                if not batch_futures:
                    logging.warning(
                        f"No valid, unique tasks submitted for Batch {batch_num + 1}. Skipping wait."
                    )
                    continue

                logging.info(
                    f"Submitted {tasks_in_batch} tasks for Batch {batch_num + 1}. Waiting for completion..."
                )

                completed_in_batch = 0
                for future in concurrent.futures.as_completed(batch_futures):
                    completed_in_batch += 1
                    try:
                        term, followed_count, found_count = future.result()
                        total_successful_follows += followed_count
                        total_profiles_found += found_count
                        logging.debug(
                            f"[Batch {batch_num+1}] Task for '{term}' completed. Success: {followed_count}, Found: {found_count}"
                        )
                    except Exception as exc:
                        # Log exceptions raised by the worker function itself
                        logging.error(
                            f"[Batch {batch_num+1}] A task generated an exception: {exc}",
                            exc_info=args.verbose,
                        )

                logging.info(
                    f"{COLOR_SEPARATOR}--- Finished Batch {batch_num + 1}/{num_batches}. Processed {completed_in_batch} tasks. ---{COLOR_RESET}"
                )
                # Optional: Add a sleep between batches if rate limits are persistent across batches
                # BATCH_SLEEP = 10 # seconds
                # if batch_num < num_batches - 1: # Don't sleep after the last batch
                #    logging.info(f"Sleeping for {BATCH_SLEEP}s before starting next batch...")
                #    time.sleep(BATCH_SLEEP)

            logging.info("All batches have been processed.")

    except FileNotFoundError:
        logging.critical(f"Error: The names file '{NAMES_FILE}' was not found.")
        sys.exit(1)
    except KeyboardInterrupt:
        logging.warning("Script interrupted by user (Ctrl+C).")
        # Consider adding cleanup or partial results summary here if needed
        sys.exit(1)
    except Exception as e:
        logging.critical(
            f"An unexpected error occurred during script execution: {e}", exc_info=True
        )
        sys.exit(1)

    # --- Final Summary ---
    print(f"{COLOR_SEPARATOR}========================================{COLOR_RESET}")
    logging.info("All tasks completed.")
    logging.info(f"Total Names Read from '{NAMES_FILE}': {names_read_count}")
    logging.info(
        f"Total Unique Cleaned Names Submitted (across all batches): {total_tasks_submitted}"
    )
    logging.info(f"Skipped Duplicate Cleaned Names: {skipped_duplicates}")
    logging.info(f"Skipped Invalid/Empty Names: {skipped_invalid}")
    logging.info(f"Total Profiles Found Across Searches: {total_profiles_found}")
    logging.info(
        f"Total Successful Follows (or Already Following): {total_successful_follows}"
    )
    logging.info("Script finished.")
    print(f"{COLOR_SEPARATOR}========================================{COLOR_RESET}")
