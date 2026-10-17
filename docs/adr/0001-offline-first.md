# ADR-0001: Offline-first PWA

## Status
Accepted

## Context
The app must work in the gym where there is no internet. The FastAPI backend runs on the home LAN, but the gym has no network connectivity to that LAN.

## Decision
The frontend is an offline-first PWA. The service worker caches the app shell on first install. Session data (sets, events, readiness) is written to IndexedDB immediately. A sync queue persists pending operations and pushes them to the FastAPI backend when the device reconnects to the home network.

## Consequences
- The user never loses logged data on reload or network drop.
- The server is not required for day-to-day logging.
- Conflict resolution favors the server (authoritative) on re-sync.
- Tailscale or other tunneling is not required for gym use.
