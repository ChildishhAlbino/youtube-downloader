# Youtube Downloader

A Python App for downloading youtube videos and playlists asyncronously.
Deploy with Docker.

1. Clone the repo
1. Create a `container.env` file and set the `OUTPUT_FILE_PATH` variable. This is the source folder on your machine that the resulting downloads will be stored in.
1. `docker compose up --build` to start the app.

## Youtube Auth
Uses OAuth2 to download videos that are age restricted, etc. This is enabled through environment variables.