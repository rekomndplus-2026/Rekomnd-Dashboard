"use client";

import { FileUploadZone } from "@/components/dashboard/FileUploadZone";
import { DataPreviewTable } from "@/components/dashboard/DataPreviewTable";
import { MessageComposer } from "@/components/dashboard/MessageComposer";
import { SendingProgress } from "@/components/dashboard/SendingProgress";
import { useState } from "react";
import { sendMessages, getConnectionState } from "@/lib/api-client";
import { toast } from "sonner";
import { CheckCircle2, ChevronRight, Radio, Smartphone } from "lucide-react";
import Link from "next/link";
import { useInstance } from "@/context/InstanceContext";
import { InstanceSelector } from "@/components/InstanceSelector";
import { useEffect } from "react";

export default function Home() {
  const [isConnected, setIsConnected] = useState(false);
  const [fileData, setFileData] = useState<any>(null);
  const [mappingConfig, setMappingConfig] = useState<any>(null);
  const [jobId, setJobId] = useState<string | null>(null);
  
  const { selectedInstance } = useInstance();

  useEffect(() => {
    let interval: NodeJS.Timeout;
    
    const checkConnection = async () => {
      try {
        const res = await getConnectionState(selectedInstance);
        const state = res.instance?.state || res.state;
        setIsConnected(state === "open");
      } catch (err) {
        setIsConnected(false);
      }
    };

    checkConnection();
    interval = setInterval(checkConnection, 5000);
    return () => clearInterval(interval);
  }, [selectedInstance]);

  const handleSend = async (template: string, mediaFilename?: string) => {
    try {
      const payload: any = {
        file_id: fileData.file_id,
        phone_column: mappingConfig.phoneColumn,
        country_code: mappingConfig.countryCode,
        message_template: template,
        instance_name: selectedInstance
      };
      
      if (mediaFilename) {
        payload.media_filename = mediaFilename;
      }
      
      const res = await sendMessages(payload);
      setJobId(res.job_id);
      toast.success("Job started successfully!");
    } catch (err: any) {
      toast.error(err.message || "Failed to start sending");
    }
  };

  return (
    <main className="min-h-screen bg-background text-foreground relative overflow-hidden font-sans">
      
      {/* Decorative background blobs using the primary color */}
      <div className="absolute top-[-20%] left-[-10%] w-[50%] h-[50%] bg-primary/10 blur-[120px] rounded-full pointer-events-none" />
      <div className="absolute bottom-[-20%] right-[-10%] w-[40%] h-[40%] bg-primary/5 blur-[120px] rounded-full pointer-events-none" />

      {/* Clean Navbar (Removed Logo for iframe) */}
      <nav className="w-full bg-background/50 backdrop-blur-md sticky top-0 z-50">
        <div className="max-w-7xl mx-auto px-6 h-16 flex items-center justify-end">
          <div className="flex items-center gap-4">
            <InstanceSelector />
            <Link
              href="/monitor"
              className="flex items-center gap-2 px-4 py-2 rounded-xl text-sm text-muted-foreground hover:text-white hover:bg-white/5 border border-transparent hover:border-border/30 transition-all"
            >
              <Radio className="w-4 h-4" />
              Group Monitor
            </Link>
          </div>
        </div>
      </nav>

      <div className="max-w-7xl mx-auto p-6 lg:py-12 relative z-10">
        <header className="mb-12">
          <h1 className="text-4xl lg:text-5xl font-black tracking-tight mb-4 text-white">
            WhatsApp Bulk Sender
          </h1>
          <p className="text-lg text-muted-foreground max-w-2xl">
            Send personalized marketing messages to thousands of contacts securely through your Rekomnd+ dashboard.
          </p>
        </header>

        <div className="grid grid-cols-1 lg:grid-cols-12 gap-8">
          {/* Left Column - Steps indicator & Connection */}
          <div className="lg:col-span-4 space-y-6">
            <div className="bg-card/40 backdrop-blur-md border border-border/40 p-6 rounded-3xl">
              <h3 className="font-bold text-lg mb-6">Workflow Status</h3>
              <div className="space-y-6">
                
                <div className={`flex items-start gap-4 transition-opacity ${isConnected ? 'opacity-100' : 'opacity-100'}`}>
                  <div className={`w-8 h-8 rounded-full flex items-center justify-center shrink-0 ${isConnected ? 'bg-primary text-primary-foreground' : 'bg-primary/20 text-primary border border-primary/30'}`}>
                    {isConnected ? <CheckCircle2 className="w-5 h-5"/> : '1'}
                  </div>
                  <div>
                    <p className={`font-bold ${isConnected ? 'text-primary' : ''}`}>Connect WhatsApp</p>
                    <p className="text-sm text-muted-foreground mt-1">Scan QR to authenticate</p>
                  </div>
                </div>

                <div className="w-0.5 h-6 bg-border/50 ml-4 -my-4"></div>

                <div className={`flex items-start gap-4 transition-opacity ${fileData ? 'opacity-100' : (isConnected ? 'opacity-100' : 'opacity-40')}`}>
                  <div className={`w-8 h-8 rounded-full flex items-center justify-center shrink-0 ${fileData ? 'bg-primary text-primary-foreground' : 'bg-primary/20 text-primary border border-primary/30'}`}>
                    {fileData ? <CheckCircle2 className="w-5 h-5"/> : '2'}
                  </div>
                  <div>
                    <p className={`font-bold ${fileData ? 'text-primary' : ''}`}>Upload Data</p>
                    <p className="text-sm text-muted-foreground mt-1">Provide your contacts CSV</p>
                  </div>
                </div>

                <div className="w-0.5 h-6 bg-border/50 ml-4 -my-4"></div>

                <div className={`flex items-start gap-4 transition-opacity ${mappingConfig ? 'opacity-100' : (fileData ? 'opacity-100' : 'opacity-40')}`}>
                  <div className={`w-8 h-8 rounded-full flex items-center justify-center shrink-0 ${mappingConfig ? 'bg-primary text-primary-foreground' : 'bg-primary/20 text-primary border border-primary/30'}`}>
                    {mappingConfig ? <CheckCircle2 className="w-5 h-5"/> : '3'}
                  </div>
                  <div>
                    <p className={`font-bold ${mappingConfig ? 'text-primary' : ''}`}>Map & Validate</p>
                    <p className="text-sm text-muted-foreground mt-1">Select phone number column</p>
                  </div>
                </div>

                <div className="w-0.5 h-6 bg-border/50 ml-4 -my-4"></div>

                <div className={`flex items-start gap-4 transition-opacity ${jobId ? 'opacity-100' : (mappingConfig ? 'opacity-100' : 'opacity-40')}`}>
                  <div className={`w-8 h-8 rounded-full flex items-center justify-center shrink-0 ${jobId ? 'bg-primary text-primary-foreground' : 'bg-primary/20 text-primary border border-primary/30'}`}>
                    {jobId ? <CheckCircle2 className="w-5 h-5"/> : '4'}
                  </div>
                  <div>
                    <p className={`font-bold ${jobId ? 'text-primary' : ''}`}>Send Messages</p>
                    <p className="text-sm text-muted-foreground mt-1">Compose & execute campaign</p>
                  </div>
                </div>
              </div>
            </div>

            {!isConnected && (
              <div className="flex flex-col items-center justify-center p-8 border border-border/50 bg-card/30 backdrop-blur-md rounded-2xl shadow-xl text-center">
                <div className="mb-4 p-4 bg-primary/10 rounded-full">
                  <Smartphone className="w-8 h-8 text-primary" />
                </div>
                <h3 className="text-xl font-bold mb-2">WhatsApp Not Connected</h3>
                <p className="text-muted-foreground text-sm">
                  Please select a connected WhatsApp number from the dropdown in the top navigation bar, or click the <strong>+</strong> button to add a new one.
                </p>
              </div>
            )}
          </div>

          {/* Right Column - Main Action Area */}
          <div className="lg:col-span-8 space-y-8">
            {jobId ? (
              <SendingProgress jobId={jobId} />
            ) : (
              <>
                {isConnected && !fileData && (
                  <div className="animate-in slide-in-from-right-8 duration-500">
                    <FileUploadZone onUploadSuccess={setFileData} />
                  </div>
                )}
                
                {fileData && !mappingConfig && (
                  <DataPreviewTable fileData={fileData} onValidated={setMappingConfig} />
                )}

                {mappingConfig && (
                  <MessageComposer columns={fileData.columns} onSend={handleSend} />
                )}
              </>
            )}

            {!isConnected && (
              <div className="h-64 border-2 border-dashed border-border/40 rounded-3xl flex items-center justify-center bg-card/10 backdrop-blur-sm">
                <p className="text-muted-foreground flex items-center gap-2">
                  Please connect WhatsApp to continue <ChevronRight className="w-4 h-4"/>
                </p>
              </div>
            )}
          </div>
        </div>
      </div>
    </main>
  );
}
