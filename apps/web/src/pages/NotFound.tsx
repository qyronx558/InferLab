import { Link } from 'react-router-dom';
import { Button } from '@/components/ui/button';
import { PageHeading } from '@/components/PageHeading';

export function NotFound() {
  return (
    <>
      <PageHeading
        eyebrow="404"
        title="Page not found"
        description="This page is not part of the demo workspace."
      />
      <Button asChild>
        <Link to="/">Back to overview</Link>
      </Button>
    </>
  );
}
