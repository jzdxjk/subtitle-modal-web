# Subtitle Cloud Translation Emby Plugin

Build with .NET SDK and copy `SubtitleCloudPlugin.dll` plus `config.html` into the Emby plugin directory.
The plugin targets `netstandard2.0` and uses the Emby 4.8 server core API for compatibility with 4.8.11 and 4.9.5.

## Current workflow

- Configure the Subtitle Cloud service URL, API token, and one mapping per line as `EmbyPrefix=ServicePrefix`.
- Open the plugin page to monitor jobs submitted through `/api/plugin/jobs`.
- Refresh state is persisted through `/api/plugin/jobs/{id}/refresh-result` with `pending`, `refreshing`, `success`, or `failed`.

The Emby server plugin SDK does not expose a stable media-item menu extension point for third-party server plugins. The plugin therefore exposes the complete authenticated task and progress API without registering a misleading runtime menu provider. A client-side menu integration can call the same endpoint with `input_path`, `emby_item_id`, `display_title`, `av_code`, and `poster_url`.

## Path mappings

Mappings use longest-prefix, case-insensitive matching. Unmatched paths are submitted unchanged.

```text
D:\\Media=/media
\\\\nas\\Movies=/mnt/movies
```
