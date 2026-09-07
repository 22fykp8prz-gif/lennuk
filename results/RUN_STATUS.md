# RUN_STATUS — reaalajas kraapimise tulemused (EE, CZ + LV, LT, FI, SE, PL)

> **Uusim seis: `results/catalog_all.csv` / `.jsonl` — 285 kirjet**
> (CZ 51, LV 21, FI 10, SE 8, PL 195 metaandmekaarti), liidetud ja
> URL-i järgi dedubleeritud kõigi jooksudest. Süvakorje 2026-09-07:
> `run --sources cz_eia,lv_vpvb,fi_yva,se_lansstyrelsen --max-docs 100`
> andis 66 uut dokumenti (CZ 33, LV 21, FI 4, SE 8; LV eelmise jooksu
> 20-dokumendi lagi sai ületatud, CENIA otsing käib nüüd search_post-i
> kaudu konfist). Renderdus töötab selles keskkonnas FI/LV jaoks
> seadetega GPS_PROXY=$HTTPS_PROXY GPS_CHROMIUM_ARGS="--ssl-version-max=tls1.2"
> GPS_IGNORE_HTTPS_ERRORS=1. KOTKAS on kinnitatult Cloudflare'i
> (govcloud.ee) taga — ka päris brauser saab siit "you have been blocked";
> Eesti vajab kohalikku jooksu (login + Smart-ID, vt README).

**Kuupäev:** 2026-09-07 (UTC)
**Haru:** `claude/gas-power-plant-scraper-58nmad`
**Käsud:** `python -m gas_plant_scraper -v run --countries EE,CZ --max-docs 20`
(+ sihitud kordusjooks CZ allikatele; + `--countries LV,LT,FI,PL,SE --max-docs 20`)

## Kokkuvõte

Esimene täisjooks andis **0 dokumenti** — iga allikas ebaõnnestus eri põhjusel
(vt tabel). Diagnoosi järel tegin Tšehhi allikatele sihitud kordusjooksu
parandatud lähte-URL-idega, mis andis **18 dokumenti** (kõik alla laetud).
Eesti portaalidest ei õnnestunud sellest keskkonnast midagi kätte saada —
põhjused on keskkonna- ja portaalipoolsed, mitte skreeperi loogika vead.

## Aruande väljund (`python -m gas_plant_scraper report`)

```
Dokumente kokku: 18
Riigi järgi:  {'CZ': 18}
MW-klassi järgi: {'<=50 MW': 11, 'teadmata': 7}
Tüübi järgi:  {'unclassified': 9, 'description': 8, 'infrastructure': 1, 'permit': 1}
```

## Allikate kaupa

| Allikas | Lehti | Dokumente | Vigu | Tulemus |
|---|---|---|---|---|
| ee_kotkas | 0 | 0 | 8 | HTTP 403 kõigile päringutele — WAF/robotitõrje |
| ee_plank | 8 | 0 | 0 | Chromiumi render ebaõnnestus (keskkonna proksi), HTTP-varuvariant sai ainult tühja SPA-kesta |
| ee_ametlikud_teadaanded | 0 | 0 | 8 | robots.txt keelab `/avalik` — skreeper austab robots.txt-d |
| cz_eia (esimene jooks) | 1 | 0 | 0 | Seemneleht näitab vaid viimaste projektide loendit; otsing nõuab POST-i |
| cz_eia (kordusjooks) | 16 | **18** | 0 | Gaasiprojektide detailvaated leitud käsitsi POST-otsinguga, seemnetena ette antud |
| cz_ippc (esimene jooks) | 0 | 0 | 1 | Konfis olev route `/ippc/ippc.nsf/vydana-povoleni` annab 404 (portaal kolis) |
| cz_ippc (kordusjooks) | 1 | 0 | 0 | Uus route `/ippc/ippc.nsf/index.xsp` avaneb, aga XPages-rakendus vajab JS-i/postback-e — linke ei ole staatilises HTML-is |

## Miks Eesti portaalid tühjaks jäid (täpsem diagnoos)

- **KOTKAS (kotkas.envir.ee)** — tagastab 403 ka täielike brauseripäistega;
  tõrje käib IP/sõrmejälje (andmekeskuse liiklus), mitte User-Agenti järgi.
  Tavabrauserist töötab. Sellest keskkonnast kättesaamatu.
- **PLANK (planeeringud.ee)** — vajab Playwrighti renderdust, aga selle
  jooksukeskkonna väljuv proksi (TLS-i vahelthaare) katkestab peata Chromiumi
  TLS-kätluse (`ERR_CONNECTION_RESET` isegi example.com-ile). Osaline
  workaround (`--ssl-version-max=tls1.2`) avas example.com-i, kuid Eesti
  hostid jäid ikka kinni. HTTP-varuvariant toob ainult SPA tühja kesta,
  sest otsing elab URL-i fragmendis (`#/planning/search`), mida server ei näe.
- **Ametlikud Teadaanded** — robots.txt keelab `/avalik/otsing` teed;
  skreeper austab seda teadlikult. Vajaks kas robots-erandit (mitte soovitatav)
  või ametlikku API-t/RSS-i.

## Teiste riikide jooks (LV, LT, FI, SE, PL) — 0 dokumenti

| Allikas | Lehti | Dokumente | Vigu | Põhjus |
|---|---|---|---|---|
| lv_vpvb | 34 | 0 | 4 | Seemnelehed avanevad, aga gaasijaama-projekte linkide kaudu ei leitud; otsingu-URL `/lv/search?q=` annab 404 (route muutunud) |
| lv_geolatvija | 6 | 0 | 0 | SPA; Chromiumi render selles keskkonnas ei tööta (proksi TLS), HTTP-varuvariant toob tühja kesta |
| lt_aaa_pav | 0 | 0 | 13 | HTTP 403 kõigile otsingupäringutele — robotitõrje |
| lt_tpdris | 0 | 0 | 1 | Ühendus lähtestatakse (nii render kui HTTP) — tõenäoliselt blokeerib andmekeskuse liiklust |
| fi_yva | 0 | 0 | 14 | HTTP 404 — ymparisto.fi otsingu-route on muutunud, `?query=` teed enam pole |
| fi_ylupa | 0 | 0 | 1 | ylupa.avi.fi TLS-sert on aegunud (`certificate has expired`); render kukub samuti |
| se_lansstyrelsen | 1 | 0 | 12 | HTTP 404 — lansstyrelsen.se otsingu-route (`/sok.html?query=`) on muutunud |
| pl_gdos_baza | 0 | 0 | 14 | Väljuv proksi ei saa hostiga ühendust (tunnel 502) — baza.gdos.gov.pl on siit kättesaamatu |
| pl_ekoportal | 0 | 0 | 1 | Portaal ise vastab HTTP 500 (`CardList.seam`) |

Kokkuvõttes: LV/LT/FI/SE vajavad peamiselt **otsingu-URL-ide uuendamist**
(routed on portaalides muutunud) ja osa (LT, ĢeoLatvija, ylupa) käivitamist
tavavõrgust päris brauseri-renderdusega. PL vajab teist võrgukeskkonda.

## Koodimuudatused selles harus (sama jooksu käigus)

- `login`-käsk: ava nähtav brauser, logi sisse Smart-ID / Mobiil-ID /
  ID-kaardiga, sessioon salvestatakse (`GPS_STORAGE_STATE`) ja seda
  kasutavad nii renderdus kui HTTP-päringud/allalaadimised. Töötab ainult
  kohalikus masinas (brauseriaken + Eesti IP).
- `search_post` seadistus POST-vormiga otsingutele; cz_eia kasutab seda
  nüüd ise (kontrollitud: leiab gaasiprojektid ilma käsitsi seemneteta).
- cz_ippc parandatud route (`index.xsp`) + render; ee_kotkas render + WAF-i
  märkus; `GPS_PROXY` ja `GPS_CHROMIUM_ARGS` keskkonnamuutujad.

## Soovitused edasiseks

1. ~~cz_eia POST-otsing~~ — **tehtud** (`search_post` seadistus töötab).
2. ~~cz_ippc route~~ — **tehtud** (`index.xsp` + render; JS-renderdus vajab
   tavavõrku).
3. **ee_kotkas / ee_plank / lt_* / lv_geolatvija / fi_ylupa**: jooksutada
   kohalikust masinast (koduvõrk + päris brauser): `python -m
   gas_plant_scraper login <url>` (Smart-ID) ja seejärel
   `GPS_STORAGE_STATE=data/storage_state.json python -m gas_plant_scraper
   run --countries EE,...` — vt README.
4. ~~lv_vpvb / fi_yva routed~~ — **parandatud** (EVA/eva.gov.lv ja
   ymparisto.fi uued teed; kontrolljooks: routed avanevad, aga dokumente
   veel ei tulnud — FI tulemused on JS-laetud otsingu taga, LV otsing ei
   leia gaasijaama-IVN projekte, register võib olla mujal).
   **se_lansstyrelsen**: otsing on JS-põhine, route vajab käsitsi
   tuvastamist brauseris.
5. **ee_ametlikud_teadaanded**: uurida ametlikku liidest (nt teadaannete
   RSS/otsepäringud), kuna robots.txt keelab otsingulehtede kraapimise.
6. **pl_gdos_baza**: siit keskkonnast kättesaamatu (proksi tunnel 502);
   proovida teisest võrgust.

## Failid

- `results/catalog.csv`, `results/catalog.jsonl` — 18 dokumendi kataloog
  (URL, projekt, tüübiklassifikatsioon, MW-hinnang, kohalik failitee).
- Allalaetud failid ise (PDF/DOC/ZIP, ~kokku 40+ MB) on `data/CZ/` kaustas,
  mis on gitignore'itud ega ole commit'is.
