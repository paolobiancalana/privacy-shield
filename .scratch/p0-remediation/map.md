# Eliminare i quattro difetti P0 di Privacy Shield
Label: wayfinder:map

## Destination
Implementare e verificare la risoluzione di revoca API key, rotazione DEK, persistenza accidentale e troncamento NER.

## Notes
La richiesta dell'utente estende esplicitamente Wayfinder all'esecuzione e ai test. Tracker locale; per configurare un altro tracker usare `/setup-matt-pocock-skills`.
Una decisione integrata: preservare gli invarianti nei percorsi concorrenti e di errore. Nessun trasferimento del vault fuori OVH UE. La chiusura locale e l'applicazione in produzione devono restare distinguibili.

## Decisions so far

- [Garantire gli invarianti P0 attraverso concorrenza e interruzioni](issues/01-security-invariants.md): patch e test completati; distinzione fra checkout locale e hardening host applicato documentata nel ticket.

## Not yet specified
Nessuna decisione di prodotto aperta; i limiti residui emergeranno dalla verifica.

## Out of scope
Altri rilievi dell'audit, certificazione ISMS, aggiornamento dipendenze e deploy applicativo non richiesto.
