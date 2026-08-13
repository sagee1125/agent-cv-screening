import type { JDDiagnosisResponse } from "../../types";
import { Card, CardContent, CardHeader, CardTitle } from "../ui/card";

interface JDDiagnosisProps {
  data: JDDiagnosisResponse | null;
}

export function JDDiagnosis({ data }: JDDiagnosisProps) {
  return (
    <Card>
      <CardHeader>
        <CardTitle className="text-base">JD Diagnosis</CardTitle>
      </CardHeader>
      <CardContent>
        {!data ? (
          <p className="text-sm text-slate-500">No diagnosis data available.</p>
        ) : (
          <div className="space-y-2">
            {data.mustSkillSatisfaction.map((item) => {
              const percent = Math.round(item.satisfactionRate * 100);
              return (
                <div key={item.skill} className="space-y-1">
                  <div className="flex items-center justify-between text-sm">
                    <span>{item.skill}</span>
                    <span className={item.flagLow ? "text-rose-600" : "text-slate-600"}>{percent}%</span>
                  </div>
                  <div className="h-2 rounded-full bg-slate-100">
                    <div
                      className={item.flagLow ? "h-2 rounded-full bg-rose-500" : "h-2 rounded-full bg-emerald-500"}
                      style={{ width: `${percent}%` }}
                    />
                  </div>
                </div>
              );
            })}
          </div>
        )}
      </CardContent>
    </Card>
  );
}
