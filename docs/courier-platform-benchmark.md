# Courier follow-up benchmark — 2 October 2026

Five established tracking platforms were reviewed through their official public product/help documentation. This is a representative feature benchmark, not a verified market-share ranking or a hands-on review of paid dashboards.

| Platform | Documented pattern | ParcelTrack implementation |
| --- | --- | --- |
| AfterShip | Shipment status tabs, exceptions, events and notification history | Status tabs, priority worklist, failed-attempt status and chronological handling history |
| Ship24 | Bulk import, courier filters, search, exports and detection overrides | Bulk imports retained; searchable, sortable and paginated list with selection and scoped CSV exports |
| TrackingMore | Shipment dashboard and configurable customer notifications | Reviewable client message draft; no automatic sends without a provider/backend |
| 17TRACK | Tags, shipment management and notification conditions | Searchable operational tags, ownership and scheduled follow-up |
| ParcelsApp | Carrier chains, local tracking numbers, event history and delivery estimates | Final-mile courier/AWB alongside original shipment, manual ETA and delivery proof reference |

## Official sources

- AfterShip: https://support.aftership.com/en/tracking/articles/15441375-manage-shipments-in-aftership-tracking
- AfterShip exceptions: https://support.aftership.com/en/tracking/articles/15441374-everything-you-need-to-know-about-exception-shipments
- Ship24 search: https://help.ship24.com/en/article/how-to-search-shipments-on-the-shipment-dashboard-vx13g6/
- Ship24 exports: https://help.ship24.com/en/article/how-to-export-data-on-the-shipment-dashboard-nxajur/
- TrackingMore notifications: https://support.trackingmore.com/en/article/email-notifications-via-trackingmore-14jgcai/
- 17TRACK tags: https://help-shopify.17track.net/en/article/how-to-add-tags-to-shipments-sxbree/
- ParcelsApp: https://parcelsapp.com/en/blog/about

## Behaviour and data boundaries

- Active means not delivered, returned or cancelled.
- Needs attention includes manually recorded exceptions/customs/failed attempts, overdue ETA, due follow-up, and no manual check in the last 24 hours.
- No movement uses recorded status-bearing events, falling back to workspace registration. Notes, edits and warehouse actions do not count as courier movement. The threshold is three days.
- Bulk assignment changes only explicitly enabled fields and never declares delivery or a carrier check.
- Client drafts omit internal notes, ownership and next actions. Users review the draft before copying; no email or WhatsApp is sent.
- Carrier overview reports recorded counts. Average days is registration-to-recorded-delivery, not transport transit time or a ranked comparison of carrier quality.
- Existing version 1 backups remain readable. Optional courier details and follow-up records are validated and included in JSON backups and CSV exports.
- Carrier APIs, predictive ETAs, webhook notifications, public tracking pages and shared team accounts require a deployed authenticated backend and credentials. This release does not simulate those capabilities.
