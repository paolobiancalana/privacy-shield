# Remediation tecnica P0 — Privacy Shield

Data: 2 ottobre 2026. Riferimento storico: [gap analysis](ISO27001_GAP_ANALYSIS_2026-10-02.md).
Il report originale e le sue riproduzioni descrivono lo stato precedente; non costituiscono test di accettazione delle patch.

## Esito e confine delle evidenze

G11, G13 e G15 implementati nel checkout locale e verificati con test unitari, di integrazione e avversariali. Le patch applicative **non sono state distribuite** al VPS e non è stato eseguito un commit/push.

G14: applicate e verificate sul VPS OVH le modifiche Nginx, swap, dump e gate di avvio. I limiti Docker e la policy Redis contenuti nel Compose aggiornato sono verificati nella configurazione renderizzata; entreranno in vigore ricreando i container. I container attuali conservano i vecchi limiti, mentre il blocco host di swap/dump è già effettivo.

Non è stato riavviato il VPS. Il gate preflight passa e il controllo va ripetuto dopo il prossimo reboot; questa sessione non dimostra un reboot completo. Nessuna modifica al sistema SSH, alla KEK o al modello. Nessuna PII cliente usata nei test. Nessuna scrittura di test nel tenant Supabase reale: le verifiche del control plane usano query mock e un'autorità simulata.

## G11 — Autorità delle API key

Con Supabase configurato, **ogni** decisione di autenticazione rilegge `ps_api_keys` con join interno all'organizzazione e al piano. Redis non può concedere accesso sulla sola base di un valore positivo già memorizzato. `active=false`, `revoked_at`, expiry raggiunta, timestamp invalido e organizzazione eliminata comportano rifiuto. Gli errori di lookup non diventano fallback su una chiave valida in cache.

La revoca dal backend aggiorna Supabase prima di invalidare Redis. La creazione di chiavi dal runtime inserisce il nuovo hash nell'autorità; il warm-up usa un metodo di sola cache separato e non può riattivare una riga. L'inserimento usa `INSERT`, mai un upsert che possa cancellare una revoca. La chiave runtime conserva il display ID `kid_*`; Supabase assegna il proprio UUID. L'organizzazione deve esistere nel control plane.

Compromesso: una lettura Supabase per richiesta, maggiore latenza e dipendenza dall'operatività del control plane. Le richieste già autorizzate e in corso non vengono annullate da una revoca successiva. Senza Supabase rimane il funzionamento standalone con autorità Redis; non deve essere usato come bypass del control plane in produzione.

File: [redis_api_key.py](../../app/infrastructure/adapters/redis_api_key.py), [supabase_api_key_loader.py](../../app/infrastructure/adapters/supabase_api_key_loader.py), [container.py](../../app/container.py), [config.py](../../app/infrastructure/config.py).

## G13 — Pubblicazione atomica e concorrenza

La rotazione acquisisce la revisione dell'organizzazione **prima** di scandire direttamente tutti i token. Non dipende dall'indice delle richieste, che potrebbe essere incompleto. Decifra e prepara tutti i nuovi ciphertext esclusivamente in memoria. Un token corrotto interrompe la preparazione: non viene scartato mentre si distrugge la sua vecchia chiave.

`WATCH/MULTI/EXEC` confronta DEK, revisione, ciphertext e record di operazione. Il commit pubblica tutti i token ancora presenti, la nuova DEK, la revisione e il risultato insieme. `SET XX KEEPTTL` conserva le scadenze, senza ricreare token scaduti o eliminati. Il cambiamento della revisione invalida anche una scansione che non avesse visto un token appena inserito.

Ogni scrittura del percorso di tokenizzazione verifica la DEK utilizzata e registra token, revisione e indice nella stessa transazione. Se una rotazione ha ritirato la DEK, il caso d'uso rilegge la chiave e ripete la cifratura, con massimo cinque tentativi. La reidratazione acquisisce DEK e ciphertext con un unico `MGET`: una rotazione successiva non mescola la chiave nuova con ciphertext vecchi già letti.

Per i retry HTTP inviare `operation_id` (1–128 caratteri) insieme a `organization_id`, riutilizzando lo stesso ID. Una risposta persa dopo `EXEC` restituisce il risultato originale al retry. I risultati sono metadati non scadenti in Redis, separati per organizzazione; persistono fino al reset del vault e non hanno persistenza su disco. Una richiesta senza ID genera una nuova operazione. La policy `volatile-ttl` impedisce l'eviction di DEK, revisioni e risultati; i record di operazione consumano RAM e vanno inclusi nel monitoraggio di capacità. La distruzione del Redis volatile elimina simultaneamente vault e record di idempotenza.

Contesa oltre il limite, errore Redis, ciphertext corrotto e token senza TTL comportano errore, non successo parziale. L'atomicità usa le garanzie delle [transazioni Redis](https://redis.io/docs/latest/develop/using-commands/transactions/); non introduce fallback non atomici. Sono testati anche errori OOM prima di `EXEC` su Redis reale. Non è un meccanismo di disaster recovery del vault volatile.

File: [vault_port.py](../../app/domain/ports/vault_port.py), [redis_vault.py](../../app/infrastructure/adapters/redis_vault.py), [rotate_dek.py](../../app/application/rotate_dek.py), [tokenize_text.py](../../app/application/tokenize_text.py), [rehydrate_text.py](../../app/application/rehydrate_text.py), [entities.py](../../app/domain/entities.py), [routes.py](../../app/infrastructure/api/routes.py), [schemas.py](../../app/infrastructure/api/schemas.py).

## G14 — Pipeline in memoria

Lo snippet Nginx usa streaming di request/response, HTTP/1.1 verso upstream, cache/store disabilitati e nessun file temporaneo di proxy su disco. Anche il buffering eccezionale del body punta a `/run/privacyshield-nginx/body`, verificato su tmpfs; le directory sono ricreate al boot da tmpfiles. `X-Accel-Buffering` dell'upstream non può riabilitare il buffering. Le direttive seguono la [documentazione Nginx](https://nginx.org/en/docs/http/ngx_http_proxy_module.html#proxy_request_buffering).

Sul VPS: `swapoff -a`, swap disabilitato in fstab e unità `swapfile.swap` masked; Apport disabilitato; `kernel.core_pattern=|/bin/false`, `fs.suid_dumpable=0`, systemd coredump `Storage=none`/`ProcessSizeMax=0`, Nginx `LimitCORE=0`. La policy sysctl si applica **dopo** l'arresto di Apport, che altrimenti ripristinerebbe `core_pattern`. Il preflight Nginx controlla tmpfs, assenza di swap e dump disabilitati prima dell'avvio.

Nel Compose: entrambi i container hanno core limit zero, filesystem read-only, tmpfs, `no-new-privileges` e limite di swap uguale al limite RAM; Redis conserva `save ""` e `appendonly no` e passa a `volatile-ttl`. Nessun backup del vault aggiunto.

Lo script rifiuta `swapoff` se recuperare le pagine lascerebbe meno di 512 MiB disponibili. Conserva backup della configurazione originaria. Il rollback verso swap/dump/buffering su disco reintrodurrebbe il difetto. Pagine o dump storici, snapshot del provider e logging applicativo del rilievo G16 non sono stati cancellati o verificati da questa remediation; non si afferma l'assenza di dati persistiti prima dell'intervento.

File: [docker-compose.yml](../../docker-compose.yml), [nginx-pii-memory.conf](../../infra/nginx-pii-memory.conf), [harden_pii_host.sh](../../scripts/harden_pii_host.sh), [check_pii_host.sh](../../scripts/check_pii_host.sh).

Verifica infrastruttura ripetibile: `ssh privacyshield 'sudo /usr/local/lib/privacyshield/check_pii_host.sh'`. Riapplicazione idempotente: trasferire `infra/` e i due script mantenendo i percorsi relativi, poi eseguire `sudo bash scripts/harden_pii_host.sh` sul VPS.

## G15 — Copertura completa degli input NER

Una sola codifica del tokenizer genera tutte le finestre fino a 512 token, con overlap di 128 token e offset riferiti al testo originale. Ogni finestra viene eseguita sul modello, i risultati duplicati/sovrapposti passano alla fusione esistente. Il numero delle finestre non è limitato a una; la coda fino al limite API di 10.000 caratteri viene elaborata.

Copertura incompleta, output di dimensione errata, valori non finiti, span invalidi o failure di una finestra fanno fallire l'intera rilevazione. Non viene restituito un risultato parziale come testo sicuro. Il meccanismo di overflow è quello del [tokenizer Hugging Face](https://huggingface.co/docs/transformers/main_classes/tokenizer).

Questo elimina il punto cieco deterministico da troncamento. Non dimostra recall del 100% del modello su ogni possibile PII: qualità semantica e false negative restano oggetto di valutazione continua. Testati modello ONNX locale equivalente a quello osservato in produzione, Unicode, confini, ultimo carattere utile e round-trip API di 10.000 caratteri.

File: [ner_detection.py](../../app/infrastructure/adapters/ner_detection.py).

## Test e riproducibilità

Esito finale: **795 test superati, nessun fallimento o skip**, 26 warning di deprecazione, 48,56 secondi. Suite P0 separata: **102 test superati**, 16,73 secondi. Verifiche crypto/span fusion/regex richieste da AGENTS: **57 superate**. `git diff --check` e sintassi Bash superati. Configurazione Nginx validata sul VPS, API health HTTP 200 e preflight riuscito.

Suite dedicata: [tests_app/security](../../tests_app/security/) (`conftest.py`, `test_key_authority.py`, `test_dek_atomicity.py`, `test_ner_windows.py`, `test_memory_config.py`). Mappa Wayfinder e ticket risolto: [map.md](../../.scratch/p0-remediation/map.md), [decisione integrata](../../.scratch/p0-remediation/issues/01-security-invariants.md). Evidenza sintetica: [P0_REMEDIATION_EVIDENCE_2026-10-02.json](P0_REMEDIATION_EVIDENCE_2026-10-02.json). Test della rotazione con contratto nuovo: [test_rotate_dek.py](../../tests_app/application/test_rotate_dek.py). Fixture port aggiornate: [conftest.py](../../tests_app/conftest.py).

I test esistenti [test_api_key_auth.py](../../tests_app/integration/test_api_key_auth.py) e [test_breach_fixes.py](../../tests_app/adversarial/test_breach_fixes.py) ora impostano esplicitamente il rate limit della fixture da verificare: l'admin API deriva i limiti dal piano e non usa il parametro deprecato passato dai vecchi test. L'asserzione dell'errore quota verifica il messaggio generico senza dettagli dell'organizzazione. Nessuna politica di rate limit applicativa indebolita per far passare i test.

La suite critica esegue i casi vault su fakeredis e su processi Redis reali isolati mediante socket Unix, senza porta pubblica né RDB/AOF. In CI è aggiunta l'installazione di `redis-server` in [ci.yml](../../.github/workflows/ci.yml). Non è stato avviato un run GitHub. Le quattro esclusioni storiche della CI restano invariate; la verifica completa locale qui riportata comprende anche quei file. I test del modello reale sono saltati se il modello locale manca; i test deterministici delle finestre restano obbligatori.

Comando completo usato, con KEK sintetica delle fixture e control plane esterno disabilitato:

```bash
PII_MODEL_DIR="$PWD/.local/pii-model" HF_HUB_OFFLINE=1 \
SUPABASE_URL='' SUPABASE_SERVICE_KEY='' PS_TEST_HOST=privacyshield \
python3 -m pytest tests_app/ -q --tb=short --disable-warnings
```

`PS_TEST_HOST` abilita due verifiche live: gate infrastruttura e body sintetico chunked oltre il buffer Nginx. Non effettua operazioni autorizzate su dati reali.

Le prove coprono revoca su cache calda/fredda/reset, scadenza esatta e timestamp invalido, cancellazione organizzazione, outage fonte, revoca/creazione durevoli, warm-up stale; rotazione interrotta, disconnect prima/dopo EXEC, idempotenza, concorrenza, isolamento tenant, lettore/scrittore concorrente, token non indicizzato, scadenza/flush/TTL, corruzione e OOM; finestre NER, Unicode, confini, output invalido, errore tardivo e round-trip API; Compose e infrastruttura live.

### Rilascio applicativo da eseguire

Prima di attestare la chiusura in produzione di G11/G13/G15: distribuire backend e Compose coerenti, ricreare i container per i nuovi limiti/policy Redis, verificare query/creazione/revoca nel tenant Supabase con una chiave di test autorizzata e rieseguire smoke e accettazione. Non mescolare istanze del vecchio e nuovo writer durante il rollout: i writer precedenti non incrementano la revisione né controllano la DEK. La ricreazione di Redis perde i token effimeri correnti come previsto; programmare il rollout dopo il drenaggio delle richieste e il TTL, senza introdurre persistenza del vault.
