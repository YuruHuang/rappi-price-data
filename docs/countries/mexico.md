# Mexico study notes

Sources and indexed listings were checked on 2026-08-16. The sample is two Mexico City delivery
points, not Mexico as a whole.

## Delivery locations

| Slug | Public address | District | Latitude | Longitude |
|---|---|---|---:|---:|
| `centro-bellas-artes` | Palacio de Bellas Artes, Av. Juárez s/n, Centro, 06050 Ciudad de México | Cuauhtémoc | 19.435470 | -99.141280 |
| `coyoacan-perisur` | Centro Comercial Perisur, Anillo Periférico Sur 4690, 04500 Ciudad de México | Coyoacán | 19.304197 | -99.190284 |

INBAL gives the [Palacio de Bellas Artes address](https://palacio.inba.gob.mx/contacto). The Mexico
City visitor site gives the [Perisur address](https://mexicocity.cdmx.gob.mx/venues/perisur/), and a
[Rappi merchant](https://www.rappi.com.mx/tiendas/1930250058-turin-mars-regalos-nc) confirms activity
at the same street number. Coordinates are the corresponding landmark points.

## Brand-qualified queries

| Category | Scope | Brands and exact queries |
|---|---|---|
| Nicotine pouches | international | ZYN — `zyn bolsas de nicotina`; VELO — `velo bolsas de nicotina`; Sesh — `sesh bolsas de nicotina` |
| Electronic cigarettes | international | Vuse — `vuse vapeador`; Elf Bar — `elf bar vapeador`; Lost Mary — `lost mary vapeador`; Geek Bar — `geek bar vapeador`; Maskking — `maskking vapeador`; WAKA — `waka vapeador`; RELX — `relx vapeador`; IPLAY — `iplay vapeador`; Esco Bars — `esco bars vapeador` |
| Electronic cigarettes | local-market | VHILL — `vhill vapeador` |
| Heated tobacco | international | IQOS — `iqos dispositivo tabaco calentado`; TEREA — `terea tabaco para iqos`; HEETS — `heets tabaco para iqos` |
| Cigarettes | international | Marlboro — `marlboro cigarrillos`; Pall Mall — `pall mall cigarrillos`; Lucky Strike — `lucky strike cigarrillos`; Camel — `camel cigarrillos`; Benson & Hedges — `benson hedges cigarrillos`; Chesterfield — `chesterfield cigarrillos`; Winston — `winston cigarrillos` |
| Cigarettes | local-market | Montana — `montana cigarrillos`; Faros — `faros cigarrillos`; Delicados — `delicados cigarrillos` |

Rappi's current [cigarette page](https://www.rappi.com.mx/retail/cigarrillos) supports the core list.
Specific evidence was also checked for [Faros](https://www.rappi.com.mx/shopping/faros),
[Montana](https://www.rappi.com.mx/p/montana-cigarrillo-shots-1483516), and a store inventory with
[Delicados and other brands](https://www.rappi.com.mx/tiendas/1930091430-apcontroladoradetiendasdec-mt-nc/cigarrillos/cigarrillos).
PMI's [Mexico portfolio](https://www.pmi.com/markets/mexico/es/overview) identifies Delicados and
Faros, while BAT's [company history](https://www.batmexico.com.mx/quienes-somos/nuestra-empresa/historia-british-american-tobacco-mexico)
supports Montana's Mexico-market relevance.

ZYN and VELO appear on Rappi's
[cigarettes and vapes page](https://www.rappi.com.mx/retail/cigarrillos-y-vapeadores); Sesh appears in
a current [Turbo inventory](https://www.rappi.com.mx/tiendas/1923301760-turbo-fresh/cigarrillos).
OUF and NIKO were left out of the default configuration because no indexed Rappi result was found.

Vape names are historical or observational detection seeds, not a current lawful-sales ranking.
Indexed pages include [Vuse](https://www.rappi.com.mx/p/vuse-vapeador-graphite-black-device-2317914),
[Elf Bar](https://www.rappi.com.mx/p/elf-bar-vaporizador-bc-5000-disposa-2209268),
[Lost Mary](https://www.rappi.com.mx/p/lost-mary-grape-2294395),
[Geek Bar](https://www.rappi.com.mx/p/geek-bar-fucking-fab-2369330), and
[Maskking](https://www.rappi.com.mx/p/maskking-vaporizador-desechable-pro-1322212). Many are marked
unavailable; preserve that status.

Current heated-tobacco evidence includes Rappi's
[IQOS/ZYN page](https://www.rappi.com.mx/retail/tienda-iqos-zyn), a
[TEREA product](https://www.rappi.com.mx/p/terea-riviera-pearl-3076256), and a legacy
[HEETS product](https://www.rappi.com.mx/p/heets-cigarrillos-yellow-27528).
Standalone IQOS/ILUMA device bodies (device/body/kit wording or a bare IQOS model title with no
TEREA/HEETS/stick evidence) are retained for audit as `heated_device` but excluded from the
four-family table. TEREA/HEETS consumables and explicitly titled welcome kits remain eligible;
welcome kits carry `study_heated_welcome_kit` and have no derived pack or unit-price denominator.

## Validated collection snapshot

The complete 2026-08-16 collection used all 32 queries at both pins. The published offline build was
regenerated on 2026-08-20 and is available as
[`datasets/mexico.xlsx`](../../datasets/mexico.xlsx); its checksum and row count are recorded in the
[release manifest](../../datasets/manifest.json). Counts below are store-location product
observations after strict four-family filtering.

| Location | Collection manifest | Raw rows | Returned stores | Pouches | E-cigarettes | Heated | Cigarettes | Final |
|---|---|---:|---:|---:|---:|---:|---:|---:|
| Bellas Artes | `20260816_174350` | 1,904 | 99 | 120 | 5 | 52 | 139 | 316 |
| Perisur | `20260816_174625` | 1,917 | 79 | 104 | 0 | 50 | 127 | 281 |
| **Combined** | 64/64 requests complete | 3,821 | — | 224 | 5 | 102 | 266 | 597 |

The vape queries returned broad search noise. Five identifiable disposable-vape listings from one
reviewed retailer SKU family survived at Bellas Artes, while none survived at Perisur. This is a
result for these pins and this time, not evidence of national availability or absence.

## Vape-law flag

Mexico's current [General Health Law](https://www.diputados.gob.mx/LeyesBiblio/pdf/LGS.pdf) includes
the reform published 2026-01-15. Articles 282 Ter and 282 Quater prohibit commercial activities,
sale, distribution, advertising, and promotion involving electronic cigarettes, vapes, and analogous
devices; personal possession and consumption not intended for those activities are excepted.

For this project, vape searches are observation only. Do not purchase, add products to a cart,
promote them, or infer legality from an indexed Rappi listing. Keep vapes analytically separate from
heated tobacco and nicotine pouches pending local legal review.
