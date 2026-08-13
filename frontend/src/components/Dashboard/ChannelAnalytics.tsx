import type { ChannelAnalyticsResponse } from "../../types";
import { Card, CardContent, CardHeader, CardTitle } from "../ui/card";

interface ChannelAnalyticsProps {
  data: ChannelAnalyticsResponse | null;
}

export function ChannelAnalytics({ data }: ChannelAnalyticsProps) {
  return (
    <Card>
      <CardHeader>
        <CardTitle className="text-base">Channel Analytics</CardTitle>
      </CardHeader>
      <CardContent>
        {!data ? (
          <p className="text-sm text-slate-500">No channel analytics yet.</p>
        ) : (
          <div className="space-y-2">
            {data.byChannel.map((item) => (
              <div key={item.sourceChannel} className="flex items-center justify-between text-sm">
                <span className="font-medium text-slate-700">{item.sourceChannel}</span>
                <span className="text-slate-600">
                  {item.candidateCount} candidates / avg {item.avgMatchScore}
                </span>
              </div>
            ))}
          </div>
        )}
      </CardContent>
    </Card>
  );
}
