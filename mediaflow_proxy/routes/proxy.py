from typing import Annotated

from fastapi import Request, Depends, APIRouter, Query, HTTPException
from fastapi.responses import StreamingResponse
import httpx

from mediaflow_proxy.handlers import (
    handle_hls_stream_proxy,
    proxy_stream,
    get_manifest,
    get_playlist,
    get_segment,
    get_public_ip,
)
from mediaflow_proxy.schemas import (
    MPDSegmentParams,
    MPDPlaylistParams,
    HLSManifestParams,
    ProxyStreamParams,
    MPDManifestParams,
)
from mediaflow_proxy.utils.http_utils import get_proxy_headers, ProxyRequestHeaders

proxy_router = APIRouter()


@proxy_router.head("/hls/manifest.m3u8")
@proxy_router.get("/hls/manifest.m3u8")
async def hls_manifest_proxy(
    request: Request,
    hls_params: Annotated[HLSManifestParams, Query()],
    proxy_headers: Annotated[ProxyRequestHeaders, Depends(get_proxy_headers)],
):
    """
    Proxify HLS stream requests, fetching and processing the m3u8 playlist or streaming the content.
    """
    return await handle_hls_stream_proxy(request, hls_params, proxy_headers)


@proxy_router.head("/stream")
@proxy_router.get("/stream")
async def proxy_stream_endpoint(
    request: Request,
    stream_params: Annotated[ProxyStreamParams, Query()],
    proxy_headers: Annotated[ProxyRequestHeaders, Depends(get_proxy_headers)],
):
    """
    Proxies stream requests to the given video URL.
    """
    # Recupera tutti gli header della richiesta originale, incluso "Range"
    headers = {key: value for key, value in request.headers.items()}

    async with httpx.AsyncClient() as client:
        upstream_response = await client.request(
            method=request.method, url=stream_params.url, headers=headers, stream=True
        )

        # Se il server upstream risponde con errore, gestiamolo correttamente
        if upstream_response.status_code in {400, 404, 416}:
            raise HTTPException(
                status_code=upstream_response.status_code,
                detail=f"Errore dal server upstream: {upstream_response.status_code}",
            )

        # Restituisce lo stream direttamente senza modificare il contenuto
        return StreamingResponse(
            upstream_response.aiter_raw(),
            status_code=upstream_response.status_code,
            headers={k: v for k, v in upstream_response.headers.items() if k.lower() != "transfer-encoding"},
        )


@proxy_router.get("/mpd/manifest.m3u8")
async def mpd_manifest_proxy(
    request: Request,
    manifest_params: Annotated[MPDManifestParams, Query()],
    proxy_headers: Annotated[ProxyRequestHeaders, Depends(get_proxy_headers)],
):
    """
    Retrieves and processes the MPD manifest, converting it to an HLS manifest.
    """
    return await get_manifest(request, manifest_params, proxy_headers)


@proxy_router.get("/mpd/playlist.m3u8")
async def playlist_endpoint(
    request: Request,
    playlist_params: Annotated[MPDPlaylistParams, Query()],
    proxy_headers: Annotated[ProxyRequestHeaders, Depends(get_proxy_headers)],
):
    """
    Retrieves and processes the MPD manifest, converting it to an HLS playlist for a specific profile.
    """
    return await get_playlist(request, playlist_params, proxy_headers)


@proxy_router.get("/proxy/hls/segment.m4s")
async def segment_endpoint(
    request: Request,
    segment_params: Annotated[MPDSegmentParams, Query()],
    proxy_headers: Annotated[ProxyRequestHeaders, Depends(get_proxy_headers)],
):
    """
    Proxies and streams a media segment, ensuring correct handling of Range requests.
    """
    # Decodifichiamo correttamente l'URL ricevuto nel parametro `d=`
    decoded_url = urllib.parse.unquote(segment_params.url)

    # DEBUG: Stampiamo l'URL per verificare che sia corretto
    print(f"DEBUG: URL richiesto al proxy: {request.url}")
    print(f"DEBUG: URL effettivo che il proxy sta cercando di raggiungere: {decoded_url}")

    # Recuperiamo tutti gli header della richiesta originale, incluso "Range"
    headers = {key: value for key, value in request.headers.items()}

    async with httpx.AsyncClient() as client:
        upstream_response = await client.get(decoded_url, headers=headers, stream=True)

        # Se il server restituisce 404, stampiamo un errore nei log
        if upstream_response.status_code == 404:
            print(f"DEBUG: Il server upstream non ha trovato il segmento: {decoded_url}")
            raise HTTPException(status_code=404, detail=f"Segmento non trovato: {decoded_url}")

        # Controlliamo se il server upstream supporta Range
        accept_ranges = upstream_response.headers.get("Accept-Ranges", "none")

        if accept_ranges.lower() == "none":
            raise HTTPException(status_code=416, detail="Il server upstream non supporta Range")

        # Inoltra il segmento senza modificarlo
        return StreamingResponse(
            upstream_response.aiter_raw(),
            status_code=upstream_response.status_code,
            headers={k: v for k, v in upstream_response.headers.items() if k.lower() != "transfer-encoding"},
        )



@proxy_router.get("/ip")
async def get_mediaflow_proxy_public_ip():
    """
    Retrieves the public IP address of the MediaFlow proxy server.
    """
    return await get_public_ip()
