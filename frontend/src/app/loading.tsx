import { LoadingBlock } from '@/components/ui';

export default function Loading() {
  return (
    <div className="card p-5">
      <LoadingBlock lines={5} />
    </div>
  );
}
