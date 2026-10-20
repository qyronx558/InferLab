import { Boxes, ArrowUpRight } from 'lucide-react';
import { Link } from 'react-router-dom';
import { PageHeading } from '@/components/PageHeading';
import { Button } from '@/components/ui/button';
import { Card, CardContent } from '@/components/ui/card';
import { useDemoData } from '@/api/hooks';

export function Models() {
  const { demoModels } = useDemoData();
  return (
    <>
      <PageHeading
        eyebrow="MODEL REGISTRY"
        title="Small models. Full context."
        description="Example registry entries for local inference exploration. No models are installed or downloaded by this interface."
      />
      <div className="grid gap-5 md:grid-cols-3">
        {demoModels.map((model) => (
          <Card key={model.id} className="shadow-none">
            <CardContent className="p-6">
              <div className="mb-6 flex items-center justify-between">
                <span className="rounded-lg border bg-slate-50 p-3 text-primary">
                  <Boxes size={23} aria-hidden="true" />
                </span>
                <span className="subtle-tag">DEMO DATA</span>
              </div>
              <h2 className="text-xl font-semibold tracking-tight">{model.name}</h2>
              <p className="mt-1 text-sm text-muted-foreground">{model.size} parameter model</p>
              <dl className="environment-list">
                <div>
                  <dt>Quantization</dt>
                  <dd>{model.quantization}</dd>
                </div>
                <div>
                  <dt>Example engine</dt>
                  <dd>Ollama</dd>
                </div>
                <div>
                  <dt>Revision</dt>
                  <dd>Demo placeholder</dd>
                </div>
                <div>
                  <dt>Availability</dt>
                  <dd>Not connected</dd>
                </div>
              </dl>
              <Button variant="outline" asChild className="w-full">
                <Link to={`/compare?left=${model.id}`}>
                  Compare example <ArrowUpRight aria-hidden="true" />
                </Link>
              </Button>
            </CardContent>
          </Card>
        ))}
      </div>
      <div className="mt-6 rounded-lg border border-dashed p-6 text-sm leading-6 text-muted-foreground">
        <strong className="text-foreground">Registry first, execution second.</strong> Real entries
        will require an approved local model, a pinned revision/checksum and licensing review.
        Arbitrary model URLs and automatic downloads are excluded.
      </div>
    </>
  );
}
