import { APP } from "@/lib/app-config";
import { Button } from "@/components/ui/button";
export function HomePage() {
  return (
    <div className="flex flex-1 items-center justify-center">
      <div className="max-w-lg text-center">
        <APP.icon className="mx-auto mb-6 size-9 text-muted-foreground" />
        <h1 className="text-3xl font-semibold tracking-tight">
          {APP.home.title}
        </h1>
        <p className="mt-3 text-muted-foreground">{APP.home.description}</p>
        <div className="mt-7 flex flex-wrap justify-center gap-3">
          <Button asChild>
            <a href="#feedback">Open feedback</a>
          </Button>
          <Button variant="outline" asChild>
            <a href="#settings">Customize appearance</a>
          </Button>
        </div>
      </div>
    </div>
  );
}
