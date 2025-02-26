from typing import Annotated

from fastapi import Request, Depends, APIRouter, Query, HTTPException
from fastapi.responses import StreamingResponse
import httpx
import urllib.parse

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
    # Recupera tutti gli header della richiesta originale
    headers = {key: value for key, value in request.headers.items()}

    async with httpx.AsyncClient() as client:
        # **Modifica**: Usa client.stream(...) invece di .request(..., stream=True)
        async with client.stream(request.method, stream_params.url, headers=headers) as upstream_response:
            # Se il server upstream risponde con un errore "nota" (400, 404, 416), rilancia un HTTPException
            if upstream_response.status_code in {400, 404, 416}:
                raise HTTPException(
                    status_code=upstream_response.status_code,
                    detail=f"Errore dal server upstream: {upstream_response.status_code}",
                )

            # Restituisce lo stream senza modificare il contenuto
            return StreamingResponse(
                upstream_response.aiter_raw(),
                status_code=upstream_response.status_code,
                headers={
                    k: v
                    for k, v in upstream_response.headers.items()
                    if k.lower() != "transfer-encoding"
                },
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


@proxy_router.head("/hls/segment.m4s")
@proxy_router.get("/hls/segment.m4s")
async def segment_endpoint(
    request: Request,
    segment_params: Annotated[MPDSegmentParams, Query()],
    proxy_headers: Annotated[ProxyRequestHeaders, Depends(get_proxy_headers)],
):
    """
    Proxies and streams a media segment, ensuring correct handling of Range requests.
    """
    # Debug: stampa i parametri
    print(f"DEBUG: Parametri ricevuti: {segment_params}")

    # Decodifica l'URL dal parametro `segment_url`
    decoded_url = urllib.parse.unquote(segment_params.segment_url)
    print(f"DEBUG: URL effettivo che il proxy sta cercando di raggiungere: {decoded_url}")

    # Recupera tutti gli header della richiesta originale, incluso "Range" (se presente)
    headers = {key: value for key, value in request.headers.items()}

    async with httpx.AsyncClient() as client:
        # **Modifica**: Usa client.stream(...) invece di .request(..., stream=True)
        async with client.stream(request.method, decoded_url, headers=headers) as upstream_response:
            # Se il server upstream restituisce 404, segnala l'errore
            if upstream_response.status_code == 404:
                print(f"DEBUG: Il server upstream non ha trovato il segmento: {decoded_url}")
                raise HTTPException(
                    status_code=404,
                    detail=f"Segmento non trovato: {decoded_url}"
                )

            # (Opzionale) Se vuoi gestire in modo esplicito il caso "Accept-Ranges: none",
            # puoi gestire qui l'eccezione 416 o ignorarla.
            #
            # accept_ranges = upstream_response.headers.get("Accept-Ranges", "none")
            # if accept_ranges.lower() == "none" and "range" in headers:
            #     raise HTTPException(status_code=416, detail="Il server upstream non supporta Range")

            return StreamingResponse(
                upstream_response.aiter_raw(),
                status_code=upstream_response.status_code,
                headers={
                    k: v
                    for k, v in upstream_response.headers.items()
                    if k.lower() != "transfer-encoding"
                },
            )


@proxy_router.get("/ip")
async def get_mediaflow_proxy_public_ip():
    """
    Retrieves the public IP address of the MediaFlow proxy server.
    """
    return await get_public_ip()
