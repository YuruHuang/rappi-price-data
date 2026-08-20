# Peru study notes

Sources and indexed listings were checked on 2026-08-16. The sample is two Lima delivery points, not
Peru as a whole.

## Delivery locations

| Slug | Public address | District | Latitude | Longitude |
|---|---|---|---:|---:|
| `miraflores-larcomar` | Centro Comercial Larcomar, Malecón de la Reserva 610, Miraflores 15074, Lima | Miraflores | -12.132220 | -77.030550 |
| `independencia-megaplaza` | Centro Comercial MegaPlaza, Av. Alfredo Mendiola 3698, Independencia 15311, Lima | Independencia | -11.994440 | -77.061150 |

[Peru Travel](https://www.peru.travel/lafinalenlima/conoce-lima/imperdibles.html) gives Larcomar's
address, and Rappi lists a [Larcomar vape merchant](https://www.rappi.com.pe/tiendas/marca-vaping-city).
MegaPlaza's [official site](https://independencia.megaplaza.com.pe/) identifies the Independencia
location, and Rappi has a [merchant at the same complex](https://www.rappi.com.pe/tiendas/72222-magellantradingperu-mt-enc).
Coordinates are the OpenStreetMap-derived mall centroids.

## Brand-qualified queries

| Category | Scope | Brands and exact queries |
|---|---|---|
| Nicotine pouches | international | ZYN — `zyn bolsas de nicotina`; VELO — `velo bolsas de nicotina`; WAKA — `waka pouches nicotina` |
| Nicotine pouches | local-market | KIK — `kik stlth pouches nicotina`; VIKA — `vika pouches nicotina`; BAGZ — `bagz pouches nicotina` |
| Electronic cigarettes | international | Vuse Go — `vuse go vapeador`; VEEV Now — `veev now vapeador`; STLTH — `stlth vapeador`; WAKA — `waka vapeador`; RELX — `relx pod vapeador`; Elf Bar — `elfbar vapeador`; Geek Bar — `geek bar vapeador`; Lost Mary — `lost mary vapeador` |
| Electronic cigarettes | local-market | Life Pod — `life pod vapeador`; Lophty — `lophty vapeador` |
| Heated tobacco | international | TEREA — `terea iqos tabaco calentado`; IQOS — `iqos iluma dispositivo tabaco calentado` |
| Cigarettes | international | Marlboro — `marlboro cigarrillos`; Lucky Strike — `lucky strike cigarrillos`; Pall Mall — `pall mall cigarrillos`; L&M — `l&m cigarrillos`; Winston — `winston cigarrillos`; Kent — `kent cigarrillos tabaco` |

Output matching treats the observed short form `Pall` as Pall Mall. It is not an extra query.

The current [Rappi cigarette page](https://www.rappi.com.pe/retail/cigarrillos) supports Marlboro,
Lucky Strike, Pall Mall, L&M, and Kent; Winston appears in a current
[store listing](https://www.rappi.com.pe/tiendas/748-cicala-catita-punta-hermosa/cigarrillos-y-vaporizadores).
No current Peru-specific cigarette brand had enough Rappi evidence, so the category contains only
international brands.

Pouch evidence comes from Rappi's [pouch page](https://www.rappi.com.pe/retail/pouches), its
[Turbo pouch aisle](https://www.rappi.com.pe/tiendas/25385-turbo-express-home/cigarrillos-y-vaporizadores/pouches),
and a [BAGZ product page](https://www.rappi.com.pe/p/bagz-nic-pouches-artic-freeze-4mg-x-1673715).
KIK has a dedicated [STLTH Peru storefront](https://pe.stlthvape.com/collections/stlth-kik).
Snus and tobacco "tab pouch" titles (observed here as `Odens`, `Siberia`, and `Vika Tab Pouches`)
contain tobacco and are classified as `smokeless_tobacco`, outside this study's tobacco-free
nicotine-pouch family; titles that state a nicotine pouch (`Vika Nic Pouches`, `Bagz Nic Pouches`)
remain eligible.

Vape evidence was checked on Rappi's [vaporizers page](https://www.rappi.com.pe/retail/vaporizadores),
[Vaping City](https://www.rappi.com.pe/tiendas/50334-3rglobalimportssac-mt-enc), and
[Indy Perú Vapes](https://www.rappi.com.pe/tiendas/68749-indy-especializada-enc). A current
[Lophty product page](https://www.rappi.com.pe/p/vape-lophty-clear-max-sandia-40000--1604001)
supports its local-market inclusion. PitayVape was not added because no indexed Rappi listing was
found.

TEREA and IQOS are the only supported heated-tobacco seeds. Evidence includes a
[current Rappi store aisle](https://www.rappi.com.pe/tiendas/24681-calavera-shop-rappimall/cigarrillos)
and a [TEREA product page](https://www.rappi.com.pe/p/terea-for-iqos-iluma-turquoise-1575369).

## Validated collection snapshot

The complete 2026-08-16 collection used all 30 queries at both pins. The included workbook was
prepared on 2026-08-20 and is available as
[`datasets/peru.xlsx`](../../datasets/peru.xlsx); its checksum and row count are recorded in the
[dataset manifest](../../datasets/manifest.json). Counts below are store-location product
observations after strict four-family filtering.

| Location | Collection manifest | Raw rows | Returned stores | Pouches | E-cigarettes | Heated | Cigarettes | Final |
|---|---|---:|---:|---:|---:|---:|---:|---:|
| Larcomar | `20260816_173738` | 3,886 | 143 | 114 | 1,766 | 0 | 359 | 2,239 |
| MegaPlaza | `20260816_174040` | 2,810 | 145 | 47 | 771 | 0 | 317 | 1,135 |
| **Combined** | 60/60 requests complete | 6,696 | — | 161 | 2,537 | 0 | 676 | 3,374 |

Fifteen retained cross-family offers (a Vuse Go puff count bundled with a VELO pouch dose) carry
`mixed_bundle`; component-specific nicotine, puff, pack, and unit-price fields are blank.

One source listing reports `Lucky Strike Cigarrillo Wild Mix 20 Und` at PEN 2,670. The value is
preserved because it is present in Rappi's raw response; it should be treated as a merchant-data
anomaly rather than silently corrected.

## Regulatory context

[Law 32159](https://busquedas.elperuano.pe/dispositivo/NL/2343203-1), published 2024-11-12, covers
tobacco, nicotine products, vapes, and heated tobacco. The latest official implementation item found
during review was the proposed regulation opened for consultation by
[MINSA Resolution 236-2026](https://www.gob.pe/institucion/minsa/normas-legales/7905925-236-2026-minsa).
Recheck whether a final regulation has been issued before collection.
