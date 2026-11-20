import { Suspense } from "react";
import { BookView } from "@/components/views/BookView";
import { Skeleton } from "@/components/ui";

export default function Page() {
  return (
    <Suspense fallback={<Skeleton className="h-96" />}>
      <BookView />
    </Suspense>
  );
}
