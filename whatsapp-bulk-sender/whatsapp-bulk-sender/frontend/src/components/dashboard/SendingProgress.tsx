"use client";

import { useEffect, useState } from "react";
import { getJobStatus } from "@/lib/api-client";
import { Progress } from "@/components/ui/progress";
import { Activity, CheckCircle2, XCircle, AlertCircle } from "lucide-react";
import { toast } from "sonner";

export function SendingProgress({ jobId, onComplete }: { jobId: string; onComplete?: () => void }) {
  const [job, setJob] = useState<any>(null);

  useEffect(() => {
    if (!jobId) return;

    let isCompleted = false;

    const poll = async () => {
      try {
        const data = await getJobStatus(jobId);
        setJob(data);

        if (data.status === "completed" || data.status === "cancelled" || data.status === "error") {
          isCompleted = true;
          if (data.status === "completed") {
            toast.success("All messages processed!");
          }
          if (onComplete) onComplete();
        }
      } catch (err) {
        console.error("Polling error:", err);
      }

      if (!isCompleted) {
        setTimeout(poll, 2000);
      }
    };

    poll();
  }, [jobId, onComplete]);

  if (!job) {
    return (
      <div className="bg-card/40 border border-border/50 p-6 rounded-3xl shadow-xl w-full text-center">
        <Activity className="w-8 h-8 text-primary animate-pulse mx-auto mb-4" />
        <p className="text-muted-foreground font-medium">Initializing job...</p>
      </div>
    );
  }

  return (
    <div className="bg-card/40 border border-border/50 backdrop-blur-md p-6 rounded-3xl shadow-xl w-full animate-in fade-in zoom-in duration-500">
      <div className="flex items-center justify-between mb-6">
        <div className="flex items-center gap-3">
          <div className={`p-2 rounded-xl ${job.status === 'completed' ? 'bg-green-500/20' : 'bg-primary/20 animate-pulse'}`}>
            <Activity className={`w-5 h-5 ${job.status === 'completed' ? 'text-green-500' : 'text-primary'}`} />
          </div>
          <h3 className="text-xl font-bold">Sending Progress</h3>
        </div>
        <div className="text-right">
          <p className="text-2xl font-black text-primary">{job.progress_percent}%</p>
          <p className="text-xs text-muted-foreground uppercase tracking-wider font-bold">{job.status}</p>
        </div>
      </div>

      <Progress value={job.progress_percent} className="h-3 mb-8 bg-secondary/50" />

      <div className="grid grid-cols-4 gap-4">
        <div className="bg-background/50 border border-border/50 rounded-2xl p-4 text-center">
          <p className="text-muted-foreground text-sm font-semibold mb-1">Total</p>
          <p className="text-2xl font-bold">{job.total}</p>
        </div>
        <div className="bg-green-500/10 border border-green-500/20 rounded-2xl p-4 text-center">
          <p className="text-green-500/80 text-sm font-semibold mb-1 flex items-center justify-center gap-1"><CheckCircle2 className="w-4 h-4"/> Sent</p>
          <p className="text-2xl font-bold text-green-500">{job.sent}</p>
        </div>
        <div className="bg-destructive/10 border border-destructive/20 rounded-2xl p-4 text-center">
          <p className="text-destructive/80 text-sm font-semibold mb-1 flex items-center justify-center gap-1"><XCircle className="w-4 h-4"/> Failed</p>
          <p className="text-2xl font-bold text-destructive">{job.failed}</p>
        </div>
        <div className="bg-orange-500/10 border border-orange-500/20 rounded-2xl p-4 text-center">
          <p className="text-orange-500/80 text-sm font-semibold mb-1 flex items-center justify-center gap-1"><AlertCircle className="w-4 h-4"/> Skipped</p>
          <p className="text-2xl font-bold text-orange-500">{job.skipped}</p>
        </div>
      </div>

      {job.results && job.results.length > 0 && (
        <div className="mt-8">
          <h4 className="text-sm font-bold text-muted-foreground uppercase tracking-wider mb-4">Recent Activity</h4>
          <div className="space-y-2 max-h-48 overflow-y-auto pr-2 custom-scrollbar">
            {[...job.results].reverse().slice(0, 10).map((res: any, idx: number) => (
              <div key={idx} className="flex items-center justify-between bg-background/30 p-3 rounded-xl border border-border/30 text-sm">
                <span className="font-mono text-muted-foreground">+{res.phone}</span>
                {res.status === 'sent' && <span className="text-green-500 font-medium flex items-center gap-1"><CheckCircle2 className="w-4 h-4"/> Sent</span>}
                {res.status === 'failed' && <span className="text-destructive font-medium flex items-center gap-1"><XCircle className="w-4 h-4"/> Failed</span>}
                {res.status === 'skipped' && <span className="text-orange-500 font-medium flex items-center gap-1"><AlertCircle className="w-4 h-4"/> Skipped</span>}
              </div>
            ))}
          </div>
        </div>
      )}
    </div>
  );
}
