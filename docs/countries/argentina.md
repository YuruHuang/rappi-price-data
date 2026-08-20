# Argentina study notes

Sources and indexed listings were checked on 2026-08-16. The sample is two Buenos Aires delivery
points, not Argentina as a whole.

## Delivery locations

| Slug | Public address | District | Latitude | Longitude |
|---|---|---|---:|---:|
| `centro-galerias-pacifico` | Av. Córdoba 550, C1054 CABA | San Nicolás, Comuna 1 | -34.599250 | -58.374779 |
| `palermo-alto-palermo` | Av. Santa Fe 3253, CABA | Palermo, Comuna 14 | -34.588402 | -58.410737 |

Galerías Pacífico's [official location page](https://www.galeriaspacifico.com.ar/ubicacion) gives
the address and map point; [Buenos Aires Tourism](https://turismo.buenosaires.gob.ar/es/otros-establecimientos/galerias-pac%C3%ADfico)
identifies it as a major San Nicolás shopping centre. Alto Palermo's
[official site](https://www.altopalermo.com.ar/) gives its address and map point, and the
[city tourism page](https://turismo.buenosaires.gob.ar/es/article/shoppings-outlets-y-centros-comerciales-cielo-abierto)
places it in Palermo.

## Brand-qualified queries

| Category | Scope | Brand | Query |
|---|---|---|---|
| Nicotine pouches | international | ZYN | `zyn pouch de nicotina` |
| Nicotine pouches | international | VELO | `velo pouch de nicotina` |
| Electronic cigarettes | international | Elf Bar | `elfbar vapeador` |
| Electronic cigarettes | international | Lost Mary | `lost mary vapeador` |
| Electronic cigarettes | international | Ignite | `ignite vapeador` |
| Electronic cigarettes | international | Geek Bar | `geek bar vapeador` |
| Electronic cigarettes | local-market | Spaceman | `spaceman vapeador` |
| Electronic cigarettes | local-market | Supreme | `supreme vapeador` |
| Heated tobacco | international | IQOS | `iqos dispositivo de tabaco calentado` |
| Heated tobacco | international | TEREA | `terea sticks de tabaco calentado` |
| Heated tobacco | international | HEETS | `heets sticks de tabaco calentado` |
| Cigarettes | international | Marlboro | `marlboro cigarrillos` |
| Cigarettes | international | Philip Morris | `philip morris cigarrillos` |
| Cigarettes | international | Lucky Strike (including Lucky and Luckies listings) | `lucky strike cigarrillos` |
| Cigarettes | international | Camel | `camel cigarrillos` |
| Cigarettes | international | Chesterfield | `chesterfield cigarrillos` |
| Cigarettes | local-market | Harmony | `harmony cigarrillos` |
| Cigarettes | local-market | Red Point | `red point cigarrillos` |
| Cigarettes | local-market | Master | `master cigarrillos` |
| Cigarettes | local-market | Melbourne | `melbourne cigarrillos` |
| Cigarettes | local-market | Dolchester | `dolchester cigarrillos` |

Output matching also normalizes the observed typo `Chesterfiel` to Chesterfield. These aliases do
not add search requests.

The cigarette list is supported by the current indexed
[Rappi cigarette aisle](https://www.rappi.com.ar/tiendas/226636-50masdrustores-mt-nc/cigarrillos-y-tabaco)
and brand pages for [Red Point](https://www.rappi.com.ar/shopping/red-point),
[Master](https://www.rappi.com.ar/shopping/master),
[Melbourne](https://www.rappi.com.ar/shopping/melbourne), and
[Dolchester](https://www.rappi.com.ar/shopping/dolchester). The national competition authority
describes Red Point and Master as Tabacalera Sarandí brands in its
[2025 decision](https://cndc.produccion.gob.ar/sites/default/files/cndcfiles/Cond1830.pdf).
[Tabacalera Espert](https://tabacaleraespert.com/) lists Melbourne, and
[Real Tabacalera](https://realtabacalera.com/empresa/) describes its Dolchester production.

The [Rappi pouch page](https://www.rappi.com.ar/retail/pouches) supported only ZYN and VELO. No
Argentina-specific pouch brand had enough current Rappi evidence, so this category was not padded.

Vape evidence came from Rappi's
[accessories catalog](https://www.rappi.com.ar/retail/accesorios-de-cigarrillos),
[vaporizers catalog](https://www.rappi.com.ar/retail/vaporizadores-y-dispositivos), and a
[Palermo store aisle](https://www.rappi.com.ar/tiendas/251831-fullser24hspalermo-mt-nc/cigarrillos/vaporizadores-y-dispositivos).
Spaceman is not Argentine-owned; it is in `local_market` because of Argentina-specific visibility.

IQOS, TEREA, and HEETS are monitoring queries. No current indexed Rappi Argentina listing was found
for them during the review, so they must not be described as currently available brands.

## Validated collection snapshot

The complete 2026-08-16 collection used all 27 queries at both pins. The published offline build was
regenerated on 2026-08-20 and is available as
[`datasets/argentina.xlsx`](../../datasets/argentina.xlsx); its checksum and row count are recorded in
the [release manifest](../../datasets/manifest.json). Counts below are store-location product
observations after strict four-family filtering. One homeware title from a decor store (a
Camel-coloured bowl filed under the cigarette aisle) is excluded as a
`study_homeware_collision`.

| Location | Collection manifest | Raw rows | Returned stores | Pouches | E-cigarettes | Heated | Cigarettes | Final |
|---|---|---:|---:|---:|---:|---:|---:|---:|
| Galerías Pacífico | `20260816_171214` | 4,429 | 120 | 74 | 36 | 0 | 715 | 825 |
| Alto Palermo | `20260816_171458` | 4,277 | 113 | 115 | 61 | 0 | 1,324 | 1,500 |
| **Combined** | 54/54 requests complete | 8,706 | — | 189 | 97 | 0 | 2,039 | 2,325 |

## Regulatory context

[Resolution 549/2026](https://www.argentina.gob.ar/normativa/nacional/norma-425443/texto), published
2026-05-04, replaced the earlier heated-tobacco prohibition and created a registration framework for
electronic-cigarette devices and liquids, heated-tobacco devices and sticks, and nicotine pouches.
[Resolution 796/2026](https://www.argentina.gob.ar/normativa/nacional/norma-427441/texto) extended
implementation timing and added warning requirements.

Rappi visibility does not prove registration or lawful sale. Record observed availability separately
and do not infer a product's regulatory status from its listing.
