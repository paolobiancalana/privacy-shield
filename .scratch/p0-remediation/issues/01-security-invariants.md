# Garantire gli invarianti P0 attraverso concorrenza e interruzioni
Type: task
Label: wayfinder:task
Status: resolved
Assignee: Codex
Parent: ../map.md
Blocked by:

## Question
Quali cambiamenti minimi e quali evidenze eseguibili garantiscono autorità Supabase a ogni autenticazione, pubblicazione atomica di DEK e ciphertext, assenza di buffering/swap/dump su disco e copertura di ogni finestra NER?

## Answer

Implementati autorità Supabase a ogni autenticazione, revoca/creazione durevoli, commit atomico di token+DEK con snapshot, CAS e idempotenza, letture e scritture concorrenti protette, finestre NER complete e gate infrastrutturale per tmpfs/swap/dump. 795 test superati, inclusi 102 P0 e controlli live OVH. La patch applicativa è locale; l'hardening host è applicato. Il rilascio applicativo e i nuovi limiti Docker restano da eseguire e verificare.

Asset: [resoconto completo](../../../docs/audit/P0_REMEDIATION_2026-10-02.md).
