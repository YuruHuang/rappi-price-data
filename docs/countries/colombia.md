# Colombia study notes

Sources and indexed listings were checked on 2026-08-16. This public-landmark profile was selected
for the four-market comparison and is separate from the addresses used in the earlier Colombia
pilot.

## Delivery locations

| Slug | Public address | District | Latitude | Longitude |
|---|---|---|---:|---:|
| `centro-plaza-bolivar` | Carrera 7 #10-47, 111711 Bogotá D.C. | La Candelaria | 4.598060 | -74.076090 |
| `chapinero-andino` | Carrera 11 #82-71, 110221 Bogotá D.C. | Chapinero | 4.666950 | -74.053126 |

The Instituto Distrital de Patrimonio Cultural's
[Plaza de Bolívar manual](https://idpc.gov.co/Transparencia/Resoluciones/2024/Manual_de_Uso_Plaza_de_Bolivar.pdf)
provides the central address. Centro Andino's
[official site](https://centroandino.com.co/andino-tourist/) provides the northern address. The
coordinates use the corresponding OpenStreetMap landmark points.

## Brand-qualified queries

| Category | Scope | Brands and exact queries |
|---|---|---|
| Nicotine pouches | international | ZYN — `zyn nicotina`; VELO — `velo nicotina` |
| Nicotine pouches | local-market | Glucloud — `glucloud nicotina` |
| Electronic cigarettes | international | Vuse — `vuse vapeador`; Lost Mary — `lost mary vapeador`; Geek Bar — `geek bar vapeador`; WAKA — `waka vapeador`; HQD — `hqd vapeador`; RELX — `relx vapeador` |
| Electronic cigarettes | local-market | Glucloud — `glucloud vapeador`; MTRX — `mtrx vapeador`; Priv Bar — `priv bar vapeador`; Mijo — `mijo vapeador` |
| Heated tobacco | international | TEREA — `terea tabaco`; HEETS — `heets tabaco`; IQOS — `iqos tabaco calentado` |
| Cigarettes | international | Marlboro — `marlboro cigarrillos`; Lucky Strike — `lucky strike cigarrillos`; Rothmans — `rothmans cigarrillos`; L&M — `l&m cigarrillos`; Chesterfield — `chesterfield cigarrillos` |
| Cigarettes | local-market | Piel Roja — `piel roja cigarrillos`; Starlite — `starlite cigarrillos`; Caribe — `caribe cigarrillos`; Mustang — `mustang cigarrillos`; Belmont — `belmont cigarrillos` |

Output matching normalizes observed spellings `Glu Cloud`, `Malboro`, `Lucky`,
`Lucky Srike`, and `LyM` to their configured brands. These aliases are not extra queries.

Current Rappi pages directly support ZYN, VELO, and Glucloud on the
[nicotine-pouch page](https://www.rappi.com.co/retail/bolsas-nicotina). Rappi's
[cigarettes and vapes page](https://www.rappi.com.co/retail/cigarrillos-y-vapeadores) shows Glucloud
and Vuse, while a current specialist aisle shows
[Geek Bar, Lost Mary, WAKA, MTRX, Priv Bar, and Mijo](https://www.rappi.com.co/tiendas/900469138-vapology-mt-nc/cigarrillos-y-vapeadores/vaporizadores).

TEREA has a current dedicated [IQOS store aisle](https://www.rappi.com.co/tiendas/900481104-pmi-mt-nc/terea).
For unit-price normalization, Rappi's
[Black Scarlet product page](https://www.rappi.com.co/p/tabaco-terea-black-scarlet-20-und-6997365)
states that a TEREA carton contains ten cajetillas of 20 sticks; the exporter uses 20 sticks for a
reviewed single-cajetilla title and multiplies by any explicit carton count.
Rappi also lists the reviewed
[L&M Blue X10 Cigarrillos Cartón](https://www.rappi.com.co/p/lym-blue-x10-cigarrillos-carton-93118)
SKU at roughly ten times the corresponding 10-stick pack price. Its incomplete `1 Und` metadata is
therefore normalized to ten 10-stick packs, or 100 sticks; the rule is limited to that exact title.
The exact EAN `7702005702417` listing `L&M Cigarrillo Carton Media Blue + 18 10 Und` is likewise
normalized to 100 sticks: its carton title and price contradict the feed's inner-pack
`1 x 10 Und` field. The reviewed `Cigarrillo Cartón Lucky Strike Atomic 10´S` title remains a
10-stick pack rather than inheriting a generic carton multiplier.

Standalone IQOS/ILUMA device bodies (device/body/kit wording or a bare IQOS model title with no
TEREA/HEETS/stick evidence) are retained for audit as `heated_device` but excluded from the
four-family table. TEREA/HEETS consumables and explicitly titled welcome kits remain eligible; a
welcome kit has no derived pack or unit-price denominator. One cannabis-shop gummy title carrying
only an mg dose is excluded as an edible collision.
The local-market cigarette selection is anchored by current Rappi pages for
[Piel Roja](https://www.rappi.com.co/shopping/piel-roja) and
[Starlite](https://www.rappi.com.co/retail/licores-y-cigarrillos), then by brands already observed and
reviewed in the earlier Colombia pilot. `local_market` records local relevance, not ownership.

## Validated collection snapshot

The complete 2026-08-16 collection used all 32 queries at both pins. The published offline build was
regenerated on 2026-08-20 and is available as
[`datasets/colombia.xlsx`](../../datasets/colombia.xlsx); its checksum and row count are recorded in
the [release manifest](../../datasets/manifest.json). Counts below are store-location product
observations after strict four-family filtering. Two Lookah Unicorn concentrate/wax devices returned
by vape searches were excluded from the nicotine-product table.

| Location | Collection manifest | Raw rows | Returned stores | Pouches | E-cigarettes | Heated | Cigarettes | Final |
|---|---|---:|---:|---:|---:|---:|---:|---:|
| Plaza de Bolívar | `20260816_173220` | 2,734 | 103 | 104 | 1,261 | 67 | 675 | 2,107 |
| Andino | `20260816_173441` | 2,790 | 100 | 209 | 1,522 | 141 | 564 | 2,436 |
| **Combined** | 64/64 requests complete | 5,524 | — | 313 | 2,783 | 208 | 1,239 | 4,543 |

Twenty retained two-vape `de regalo` offers carry `mixed_bundle`; component-specific nicotine,
puff, pack, and unit-price fields are blank.

## Interpretation

The Andino and Plaza de Bolívar pins are meant for cross-country comparability. Do not combine these
observations with a different location profile without an explicit sampling decision.
