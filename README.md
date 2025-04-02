# Zora Batch Profile Follower

This Python script automates the process of finding and following Zora profiles based on a list of names provided in a text file (`names.txt`). It uses the Zora API for searching profiles and the Zora GraphQL API for following them. The script processes names in batches, utilizes threading for concurrency, and includes configurable delays to help manage potential API rate limits.

## Features

*   **Batch Processing:** Reads names from `names.txt` and processes them in configurable batches.
*   **Profile Searching:** Searches for Zora profiles matching the names provided.
*   **Automated Following:** Attempts to follow the profiles found via the Zora GraphQL API.
*   **Concurrency:** Uses `ThreadPoolExecutor` to perform search and follow operations concurrently.
*   **Rate Limiting Management:** Includes configurable sleep timers between follow actions and task submissions.
*   **Authentication:** Requires a Zora Bearer authentication token.
*   **Name Cleaning:** Cleans input names to use only ASCII alphabetic characters for searching.
*   **Duplicate Handling:** Skips processing duplicate cleaned names.
*   **Configurable Identifier:** Option to use either `profileId` or `handle` from search results for following.
*   **Colored Logging:** Provides readable, colored console output for different log levels (requires `colorama`).
*   **Verbose Mode:** Offers a `-v` or `--verbose` flag for detailed DEBUG level logging.
*   **Error Handling:** Includes basic handling for network errors, HTTP errors (including rate limits), and API response issues.
*   **Summary Report:** Outputs a summary of actions taken upon completion.

## Prerequisites

*   Python 3.x
*   `requests` library
*   `colorama` library (Optional, for colored terminal output)

## Setup & Installation

1.  **Clone or Download:** Get the script file (`zora_batch_follower.py` - assuming you save the code with this name).
2.  **Install Dependencies:**
    ```bash
    pip install requests colorama
    ```
    *(Note: `colorama` is optional but recommended for better log readability).*
3.  **Create `names.txt`:** Create a file named `names.txt` in the same directory as the script. Add the names you want to search for, with one name per line. Example:
    ```
    AliceZora
    BobOnchain
    CreativeDAO
    Another User
    ```
4.  **Obtain Zora Auth Token:**
    *   You need a valid Bearer token from an authenticated Zora session.
    *   **Method:** Typically, this involves logging into Zora.co in your web browser, opening the browser's developer tools (usually F12), going to the "Network" tab, performing an action that requires authentication (like following someone), finding a relevant API request (e.g., to `api.zora.co` or `zora.co/api`), and inspecting the request headers to find the `Authorization` header. The value will look like `Bearer eY...`. Copy the *entire* token string (including `Bearer ` if the script doesn't add it, but this script expects *just* the token part after `Bearer `).
    *   **Security:** Keep this token secure! Do not share it. It grants access to your account.
5.  **Set Authentication Token:** You have two options:
    *   **(Recommended) Environment Variable:** Set an environment variable named `ZORA_AUTH_TOKEN` with your token value.
        *   *Linux/macOS:* `export ZORA_AUTH_TOKEN="eY..."`
        *   *Windows (cmd):* `set ZORA_AUTH_TOKEN=eY...`
        *   *Windows (PowerShell):* `$env:ZORA_AUTH_TOKEN="eY..."`
    *   **(Not Recommended) Hardcode:** Directly replace the placeholder `"eY........."` in the `AUTH_TOKEN` variable within the script. This is less secure.

## Configuration

You can adjust the script's behavior by modifying the constants near the top of the file:

*   `AUTH_TOKEN`: Set via environment variable (preferred) or by editing the script. **Must be changed from the placeholder.**
*   `NAMES_FILE`: The name of the file containing the list of names (default: `"names.txt"`).
*   `MAX_WORKERS`: The number of concurrent threads to use for processing search terms (default: `1`). Increase for potentially faster processing, but be mindful of rate limits.
*   `SLEEP_DURATION_FOLLOW`: Seconds to pause between follow attempts *for profiles found from the same search term* (default: `3`). Increase if you encounter rate limits during the follow step.
*   `SLEEP_DURATION_SEARCH_SUBMIT`: Seconds to pause between submitting each search task *within a batch* (default: `0.1`). Can help throttle the rate of search requests.
*   `EXTRACT_PROFILE_ID_FIELD`: Set to `True` to use the `profileId` found in search results for following. Set to `False` to use the `handle` (default: `True`). Ensure the chosen field is what the follow API expects.
*   `BATCH_SIZE`: Number of names to process in each batch (default: `30`).

## Usage

1.  Navigate to the directory containing the script and `names.txt`.
2.  Run the script from your terminal:

    ```bash
    python zora_batch_follower.py
    ```

3.  For more detailed output (including debug messages, full API responses for non-search requests), use the verbose flag:

    ```bash
    python zora_batch_follower.py -v
    ```
    or
    ```bash
    python zora_batch_follower.py --verbose
    ```

The script will output logs indicating its progress, including names being searched, profiles found, follow attempts, successes, failures, and rate limit warnings. A final summary will be printed upon completion or interruption.

## Important Notes & Disclaimer

*   **API Usage & Rate Limits:** This script interacts directly with Zora's APIs. Excessive use or high concurrency (`MAX_WORKERS`) might lead to temporary or permanent rate limiting or IP bans from Zora. Use responsibly and adjust `MAX_WORKERS`, `BATCH_SIZE`, and sleep durations if you encounter `429 Too Many Requests` errors.
*   **Terms of Service:** Using automated scripts like this may violate Zora's Terms of Service. Use at your own risk. The author is not responsible for any consequences resulting from the use of this script.
*   **Authentication Token Security:** Your Zora authentication token is sensitive. Protect it like a password. Using environment variables is safer than hardcoding it into the script.
*   **API Changes:** Zora might change its API endpoints, request/response formats, or authentication methods at any time, which could break this script.
*   **No Guarantees:** The script attempts to follow profiles but doesn't guarantee success for every profile found. Some profiles might be invalid, already followed, or the API might return errors. The script logs these outcomes.
*   **Ethical Use:** Use this script responsibly and ethically. Avoid spamming or disrupting the Zora platform.
