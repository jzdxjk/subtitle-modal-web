# JavDB Node Selector Design

## Goal

Replace the single DBO configuration block with a unified metadata provider selector matching the supplied screenshots.

## Nodes

The selector lists five nodes: four fixed JavDB mirrors and one custom DBO node. The DBO URL and API key remain user-configurable. The selected node is persisted in application configuration.

## Behavior

- The configuration card shows the selected API URL and opens a node selection dialog.
- The dialog probes all nodes and displays availability, resolved IP, latency, and the current selection.
- Each row can be probed independently; the header action probes all rows.
- Selecting a JavDB node uses signed `/api/v2/search` requests and direct CDN image proxying.
- Selecting DBO uses its custom URL, `X-API-Key`, `/api/search`, and `/api/image` contract.
- JavDB searches retry the other JavDB mirrors when the selected mirror is unavailable. DBO does not silently switch providers.

## Security

The JavDB signing secret remains server-side. The image proxy accepts only HTTP(S) URLs and restricts remote image hosts. DBO credentials remain redacted in configuration responses.

## Compatibility

The browser continues to call `/api/dbo-search`; the backend turns it into a provider-neutral compatibility route so existing poster loading and caching remain intact.
