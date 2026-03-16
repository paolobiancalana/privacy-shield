import Link from "next/link";
import { Button } from "@/components/ui/button";
import {
  Card,
  CardContent,
  CardHeader,
  CardTitle,
  CardDescription,
  CardFooter,
} from "@/components/ui/card";
import { Badge } from "@/components/ui/badge";
import { Check, Sparkles } from "lucide-react";

const betaFeatures = [
  "200 richieste / minuto",
  "500.000 token / mese",
  "20 chiavi API",
  "10 tipi di entità PII (specifici per l'Italia)",
  "Sicurezza trasporto mTLS",
  "Latenza p99 inferiore a 80ms",
  "Gestione dati conforme al GDPR",
  "Cifratura token AES-256",
  "Supporto via email",
];

export default function PricingPage() {
  return (
    <div className="px-6 py-24">
      <div className="mx-auto max-w-3xl text-center">
        <Badge
          variant="outline"
          className="mb-4 border-emerald-500/40 bg-emerald-500/10 text-emerald-400"
        >
          <Sparkles className="mr-1 h-3 w-3" />
          Programma Beta
        </Badge>
        <h1 className="text-4xl font-bold tracking-tight text-foreground">
          Gratuito durante la Beta
        </h1>
        <p className="mt-4 text-lg text-muted-foreground">
          Accesso completo a Privacy Shield durante la fase beta. Nessuna carta
          di credito richiesta. Aiutaci a migliorare il prodotto e mantieni
          l&apos;accesso al lancio dei piani a pagamento.
        </p>
      </div>

      <div className="mx-auto mt-12 max-w-lg">
        <Card
          className="relative"
          style={{
            borderColor: "#10b981",
            boxShadow:
              "0 0 0 1px #10b981, 0 8px 32px rgba(16,185,129,0.15)",
          }}
        >
          <div className="absolute -top-3 left-1/2 -translate-x-1/2">
            <Badge className="bg-emerald-600 text-white hover:bg-emerald-600">
              Piano attivo
            </Badge>
          </div>

          <CardHeader className="pb-2 text-center">
            <CardTitle className="text-2xl">Accesso Beta</CardTitle>
            <CardDescription>
              Accesso completo alla piattaforma mentre perfezioniamo il prodotto
            </CardDescription>
          </CardHeader>

          <CardContent className="flex flex-col gap-6">
            <div className="text-center">
              <span className="text-5xl font-bold tracking-tight text-emerald-400">
                €0
              </span>
              <span className="ml-2 text-sm text-muted-foreground">
                per tutta la durata della beta
              </span>
            </div>

            <ul className="flex flex-col gap-2.5">
              {betaFeatures.map((feat) => (
                <li
                  key={feat}
                  className="flex items-center gap-2.5 text-sm text-foreground"
                >
                  <Check
                    className="h-4 w-4 shrink-0"
                    style={{ color: "#10b981" }}
                    aria-hidden="true"
                  />
                  {feat}
                </li>
              ))}
            </ul>
          </CardContent>

          <CardFooter>
            <Link href="/signup" className="w-full">
              <Button className="w-full" size="lg">
                Inizia la Beta
              </Button>
            </Link>
          </CardFooter>
        </Card>
      </div>

      {/* Coming soon */}
      <div className="mx-auto mt-16 max-w-2xl text-center">
        <h2 className="text-xl font-semibold text-foreground">
          Piani a pagamento in arrivo
        </h2>
        <p className="mt-3 text-sm text-muted-foreground">
          Stiamo lavorando a piani Developer, Business ed Enterprise con limiti
          più elevati, infrastruttura dedicata e supporto prioritario. Gli utenti
          beta avranno accesso a prezzi agevolati al lancio.
        </p>
        <p className="mt-4 text-sm text-muted-foreground">
          Domande?{" "}
          <a
            href="mailto:info@privacyshield.pro"
            className="underline underline-offset-4 transition-colors hover:text-foreground"
          >
            Contattaci
          </a>
        </p>
      </div>
    </div>
  );
}
