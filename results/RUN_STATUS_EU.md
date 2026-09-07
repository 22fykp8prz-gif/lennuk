# RUN_STATUS_EU — reaalajas kraapimise tulemused (LV, LT, FI, SE, PL)

**Kuupäev:** 2026-09-07 (UTC)
**Haru:** `claude/gas-power-plant-scraper-58nmad`
**Käsud:**
1. `python -m gas_plant_scraper -v run --countries LV,LT,FI,SE,PL --max-docs 20`
2. sihitud kordusjooks parandatud konfiguratsiooniga:
   `python -m gas_plant_scraper -v run --sources lv_vpvb,fi_yva,se_lansstyrelsen --max-docs 20`
3. API-põhised sihitud kogumised fi_ylupa ja pl_ekoportal jaoks (vt allpool)

## Kokkuvõte

Esimene täisjooks andis **0 dokumenti** — kõigil allikatel olid kas vananenud
URL-id (portaalireformid LV-s, FI-s ja SE-s), võrgutõkked (LT, PL gdos) või
roomajale nähtamatud manuselingid. Pärast diagnoosi ja parandusi kogunes
**233 kirjet**: 38 alla laetud dokumenti (LV 20, FI 10, SE 8) ja 195 Poola
KMH-registri metaandmekaarti. Kõik parandused on kantud `config/sources.yaml`-i
ja koodi (vt "Kooditäiendused").

## Aruande väljund (`python -m gas_plant_scraper report`)

```
Dokumente kokku: 233
Riigi järgi:  {'FI': 10, 'LV': 20, 'PL': 195, 'SE': 8}
MW-klassi järgi: {'<=100 MW': 2, '<=20 MW': 9, '<=200 MW': 12, '<=50 MW': 4, '>200 MW': 32, 'teadmata': 174}
Tüübi järgi:  {'unclassified': 147, 'permit': 64, 'infrastructure': 16, 'description': 15, 'safety': 4, 'drawing': 2}
```

(Suur "teadmata"/"unclassified" osakaal tuleb PL metaandmekaartidest, mille
juurde faile ei avaldata — klassifitseerida sai vaid pealkirja järgi.)

## Allikate kaupa

| Allikas | Jooks | Lehti | Dokumente | Vigu | Tulemus |
|---|---|---|---|---|---|
| lv_vpvb | 1. | 34 | 0 | 4 | Vana seed 404; manuselingid laiendita (`/lv/media/NNN/download`) jäid tuvastamata |
| lv_vpvb | 2. | 28 | **20** (kõik alla laetud) | 0 | Parandatud seed + `/download`-heuristika; `--max-docs 20` lagi sai täis |
| lv_geolatvija | 1. | 6 | 0 | 0 | TAPIS renderdub, aga otsing indekseerib ainult planeeringute (koha)nimesid — gaasijaama märksõnad ei anna midagi |
| lt_aaa_pav | 1. | 0 | 0 | 13 | Cloudflare'i JS-väljakutse (403 "Just a moment") — ka peata Chromium ei läbi |
| lt_tpdris | 1. | 0 | 0 | 1 | tpdris.lt lähtestab kõik ühendused (ka curl) — blokeerib andmekeskuse liiklust |
| fi_yva | 1. | 0 | 0 | 14 | ymparisto.fi restruktureeriti: vanad URL-id 404 |
| fi_yva | 2. | 19 | **4** (alla laetud 4) | 0 | Uus seed `/fi/yva-hankkeet` + `/fi/search?q=` renderdusega; YVA-projektide lausunnot/selostused |
| fi_ylupa | 1. | 1 | 0 | 0 | Teenus kolis ytietopalvelu.lvv.fi-le; asjalehed on Blazor-WASM, dokumendilinke `<a>`-dena DOM-is pole |
| fi_ylupa | API | – | **6** (alla laetud 6) | 0 | Sihitud kogumine otsingu-API kaudu: 6 gaasiturbiini/-mootorijaama loaotsust |
| se_lansstyrelsen | 1. | 1 | 0 | 12 | Konfis olnud `/sok.html` annab 404 |
| se_lansstyrelsen | 2. | 13 | **8** (alla laetud 8) | 0 | Töötav otsing `/stockholm/sokresultat.html?query=`; temaatilised aruanded (mitte projektiload) |
| pl_gdos_baza | 1. | 0 | 0 | 14 | Väljuv proksi ei saa tunnelit püsti (CONNECT 502) — host on sellest keskkonnast kättesaamatu |
| pl_ekoportal | 1. | 0 | 0 | 1 | Roboti User-Agent saab HTTP 500; portaal on nüüd React-SPA |
| pl_ekoportal | API | – | **195** (metaandmed, faile ei avaldata) | 0 | Sihitud kogumine `apiv1/cards` kaudu LIKE-mustritega |

## Portaalide diagnoosid (miks esimene jooks tühjaks jäi)

- **lv_vpvb → eva.gov.lv** — Vides pārraudzības valsts birojs on liidetud ja
  vpvb.gov.lv suunab nüüd www.eva.gov.lv-le; vana seed-tee annab seal 404
  (õige on `/lv/ietekmes-uz-vidi-novertejumu-projekti`, NB "novertejumu").
  Teine, olulisem viga: projektilehtede manused on Drupali laiendita lingid
  kujul `/lv/media/NNNN/download?attachment`, mida faililaiendil põhinev
  tuvastus ei näinud. Lisasin roomajasse `/download`-lõpuga URL-ide
  heuristika — pärast seda 20 dokumenti (KMH-atzinum'id, otsused, ziņojum'id
  nt Gren Latvija koģenerācijas jaama projektist). Host on aeglane
  (~670 KB loendileht aegus mõnikord 30 s piiril; õnnestus kordusega).
- **lv_geolatvija (TAPIS)** — SPA renderdub Chromiumis ilusti ja API on
  olemas (`/api/v1/tapis/planned-documents-search?search=...`), aga see
  otsib ainult planeeringudokumentide nimedest ("X novada teritorijas
  plānojojums"), mitte sisust — gaasijaama märksõnad annavad 0 vastet.
  Teemapõhiseks otsinguks see register ei sobi; vaja oleks planeeringu
  nime/asukohta ette teada.
- **lt_aaa_pav (aaa.lrv.lt)** — kogu lrv.lt-portaaliperekond on Cloudflare'i
  JS-väljakutse taga; 403 + "Just a moment" nii requests'ile kui ka peata
  Chromiumile (andmekeskuse IP + peata brauseri sõrmejälg). Sellest
  keskkonnast kättesaamatu; gamta.lt (vana AAA sait) vastab, kuid PAV
  dokumente seal enam ei publitseerita.
- **lt_tpdris (tpdris.lt)** — server lähtestab TCP-ühenduse enne TLS-i
  (ka curl'iga), tõenäoliselt geo-/andmekeskuse blokk. Kättesaamatu.
- **fi_yva (ymparisto.fi)** — sait ehitati 2024/25 ümber: vana
  `/fi/osallistu-ja-vaikuta/.../yva-hankkeet` ja otsing `/fi/haku` annavad
  404. Uus loend on `/fi/yva-hankkeet` ja otsing `/fi/search?q=...`, mis on
  kliendipoolne React-rakendus (Elastic app-search) — vajab renderdust.
  Mõlemad parandused konfis; teine jooks tõi 4 YVA-dokumenti
  (>200 MW jaamaprojektide arviointiohjelma/selostuse lausunnot).
- **fi_ylupa → ytietopalvelu.lvv.fi** — AVI-de lupateenistus kolis 2026-01
  ameti reformiga (Lupa- ja valvontavirasto) uuele aadressile;
  ylupa.avi.fi suunab sinna. Rakendus on Blazor-WASM: otsing käib
  `POST /api/v1/cases/search` (JSON `{type:0, query, offset:0, fetchNext:0}`),
  asja dokumendiloend `GET /api/v1/cases/actions/{caseId}` ja fail
  `GET /api/v1/documents/attachment/{attachmentId}`. Asjalehed EI sisalda
  tavalisi `<a>`-linke, seega üldine roomaja jääb tühjaks ka renderdusega.
  Sihitud API-kogumine (skript, sama loogika mis CZ POST-otsingul) andis
  6 asjast 6 loaotsuse PDF-i: Kellosaari GT (Helen Oy), Nokia GT (K5),
  Porvoo rafineerimistehase GT KTVL2, Tornio gaasimootorijaam, Mertaniemi
  gaasimootorijaam (Lappeenranta), Vatajankoski.
- **se_lansstyrelsen** — üleriigiline `/sok.html` on kadunud (404); otsing
  elab maakonna prefiksi all (`/stockholm/sokresultat.html?query=...`,
  serveripoolne HTML). Parandatud konfis; 8 PDF-i. NB: sisu on
  temaatilised aruanded (elektrifitseerimise kavad, kaugkütte turvalisus,
  gaasitehaste saastunud alade inventuur), mitte projektide loadokumendid —
  Rootsis projektiload avalikus veebiportaalis ei ole, neid tuleb küsida
  diariumist (offentlighetsprincipen).
- **pl_gdos_baza (baza.gdos.gov.pl)** — keskkonna väljuv proksi ei saa
  hostiga CONNECT-tunnelit püsti (502 igal katsel, ka curl). Kättesaamatu
  sellest keskkonnast; tavavõrgust tasub uuesti proovida.
- **pl_ekoportal (wykaz.ekoportal.pl)** — kaks eripära: (1) roboti
  User-Agent saab HTTP 500, brauseri-UA töötab; (2) vana JSF-rakendus on
  asendatud React-SPA-ga, mille taga on JSON-API:
  `GET /apiv1/cards/{lk}?tytul=<muster>&per_page=N` (NB: `tytul` on
  SQL-LIKE — kasuta `%...%` alamstringiotsinguks), detailid
  `GET /apiv1/describe_card/{id}`, inimloetav leht `/dokument/{id}`.
  Register on **ainult metaandmed**: kaart ütleb, mis dokument on ja mis
  ametiasutuses seda hoitakse; faile ei avaldata. Kogusin 195 gaasijaama-
  teemalist kaarti (turbiny gazowej, gazowo-parowy, silniki gazowe,
  elektrociepłownia gazowa jm mustrid) — igaühel projekt, dokumenditüüp
  ja hoidev asutus, mille kaudu saab dokumendi välja nõuda.
  Metaandmekirjeid ei piiratud `--max-docs 20`-ga, sest faile alla ei
  laetud (piirang on mõeldud allalaadimismahule).

## Kooditäiendused (committed)

- `gas_plant_scraper/browser.py` — Chromium käivitatakse
  `--ssl-version-max=tls1.2` lipuga (keskkonna TLS-i vahelt haarav proksi
  lähtestab TLS 1.3 kätluse; eelmises jooksus diagnoositud probleem) ja
  kontekst `ignore_https_errors=True` (proksi allkirjastab sertid oma
  CA-ga, mida Chromiumi pood ei tunne; nt ylupa.avi.fi andis
  ERR_CERT_DATE_INVALID). Ilma nendeta ei renderdu ükski SPA-allikas
  selles keskkonnas; nendega renderdusid kõik peale Cloudflare'i-tõkkega
  aaa.lrv.lt ja võrgutasandil blokitud tpdris.lt.
- `gas_plant_scraper/crawler.py` — `_is_document_url` tunneb nüüd ära ka
  laiendita Drupali-manused (tee lõpp `/download`), ilma milleta LV
  dokumendid jäänuks nähtamatuks.
- `config/sources.yaml` — lv_vpvb (EVA seed/otsing/domeenid), fi_yva
  (uus seed + renderdatav otsing), fi_ylupa (uus domeen + API kirjeldus
  notes'is), se_lansstyrelsen (töötav otsingu-URL), lt_aaa_pav
  (Cloudflare'i märkus).

## Failid

- `results/catalog_eu.csv`, `results/catalog_eu.jsonl` — 233 kirje kataloog
  (URL, allikas, pealkiri, tüübiklassifikatsioon, MW-hinnang, failitee).
- Allalaetud failid (38 tk, ~45 MB: LV 15 MB, FI 8,7 MB, SE 21 MB) on
  `data/` kaustas, mis on gitignore'itud ega ole commit'is.
- Eelmise jooksu EE+CZ tulemused: `results/RUN_STATUS.md`,
  `results/catalog.csv/.jsonl` (18 CZ dokumenti).

## Soovitused edasiseks

1. **fi_ylupa**: teha API-põhine adapter osaks paketist (praegu sihitud
   skript) — otsing + actions + attachment on stabiilne JSON-API ja katab
   kogu Soome keskkonnalubade arhiivi. Tasub proovida ka rohkemate
   märksõnadega ("voimalaitos", "kaasukombi", jaamade nimed).
2. **pl_ekoportal**: sama — API-adapter, mis kataloogib kaardid ja lisab
   hoidva asutuse kontakti; dokumendid tuleb asutustelt eraldi küsida.
   `tytul`-LIKE mustrid töötavad hästi; kaaluda ka `zakres`-välja.
3. **pl_gdos_baza, lt_tpdris, lt_aaa_pav, ee_kotkas**: jooksutada
   elukoha-/kontorivõrgust — kõik neli tõket on IP-/keskkonnapõhised,
   mitte skreeperi vead.
4. **lv_geolatvija (TAPIS)**: kasutada teemaotsingu asemel teadaolevate
   projektide nimesid/asukohti (nt EVA IVN-projektidest leitud omavalitsus
   + "lokālplānojums").
5. **se_lansstyrelsen**: projektidokumentideks pärida diariumist; kaaluda
   ka mark- och miljödomstol'ite avalikke otsingu(vero)teenuseid.
6. **LV mahu suurendamiseks**: tõsta `--max-docs` (20 sai täis) ja lisada
   EVA otsingusse rohkem termineid (nt "TEC", "biogāzes koģenerācija").
