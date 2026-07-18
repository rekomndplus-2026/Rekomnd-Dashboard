"use client";

import { useState, useEffect } from "react";
import { Loader2, QrCode, Smartphone, CheckCircle2 } from "lucide-react";
import { createSession, getSessionStatus, getQrCode } from "@/lib/api-client";
import { Button } from "@/components/ui/button";

export function QRCodeWidget({ onConnected }: { onConnected: () => void }) {
  const [status, setStatus] = useState<"connecting" | "qr_code" | "connected" | "error" | "disconnected">("disconnected");
  const [qrBase64, setQrBase64] = useState<string | null>(null);
  const [phone, setPhone] = useState<string | null>(null);

  const initSession = async () => {
    setStatus("connecting");
    try {
      const res = await createSession();
      if (res.status === "qr_code" && res.qr_code) {
        setQrBase64(res.qr_code);
        setStatus("qr_code");
      } else if (res.status === "connected") {
        setPhone(res.phone_number);
        setStatus("connected");
        onConnected();
      } else {
        fetchQrCode();
      }
    } catch (error) {
      console.error(error);
      setStatus("error");
    }
  };

  const fetchQrCode = async () => {
    try {
      const res = await getQrCode();
      if (res.status === "qr_code" && res.qr_code) {
        setQrBase64(res.qr_code);
        setStatus("qr_code");
      }
    } catch (error) {
      console.error(error);
    }
  };

  useEffect(() => {
    let interval: NodeJS.Timeout;
    if (status === "qr_code" || status === "connecting") {
      interval = setInterval(async () => {
        try {
          const res = await getSessionStatus();
          if (res.status === "connected") {
            setPhone(res.phone_number);
            setStatus("connected");
            onConnected();
            clearInterval(interval);
          } else if (res.status === "qr_code" && res.qr_code) {
            setQrBase64(res.qr_code);
            setStatus("qr_code");
          }
        } catch (error) {
          // Ignore polling errors
        }
      }, 3000);
    }
    return () => clearInterval(interval);
  }, [status, onConnected]);

  return (
    <div className="flex flex-col items-center justify-center p-6 border border-border/50 bg-card/30 backdrop-blur-md rounded-2xl shadow-xl transition-all duration-300">
      <div className="mb-4 p-3 bg-primary/10 rounded-full">
        <Smartphone className="w-8 h-8 text-primary" />
      </div>
      
      <h3 className="text-xl font-bold mb-2">WhatsApp Connection</h3>
      
      {status === "disconnected" && (
        <div className="text-center">
          <p className="text-muted-foreground mb-6 text-sm">Link your WhatsApp to start sending bulk messages securely.</p>
          <Button onClick={initSession} className="w-full bg-primary hover:bg-primary/90 text-primary-foreground font-semibold rounded-xl">
            Generate QR Code
          </Button>
        </div>
      )}

      {status === "connecting" && (
        <div className="flex flex-col items-center animate-pulse">
          <Loader2 className="w-10 h-10 text-primary animate-spin mb-4" />
          <p className="text-muted-foreground font-medium">Initializing session...</p>
        </div>
      )}

      {status === "qr_code" && qrBase64 && (
        <div className="flex flex-col items-center animate-in fade-in zoom-in duration-500">
          <div className="bg-white p-3 rounded-2xl shadow-inner mb-4">
            <img src={qrBase64.startsWith('data:image') ? qrBase64 : `data:image/png;base64,${qrBase64}`} alt="QR Code" className="w-48 h-48 rounded-lg" />
          </div>
          <p className="text-sm text-muted-foreground font-medium flex items-center gap-2">
            <Loader2 className="w-4 h-4 animate-spin text-primary" /> Waiting for scan...
          </p>
        </div>
      )}

      {status === "connected" && (
        <div className="flex flex-col items-center animate-in zoom-in duration-300">
          <div className="w-16 h-16 bg-green-500/20 rounded-full flex items-center justify-center mb-4">
            <CheckCircle2 className="w-8 h-8 text-green-500" />
          </div>
          <p className="text-green-500 font-semibold mb-1">Successfully Connected</p>
          <p className="text-muted-foreground text-sm font-mono bg-muted/50 px-3 py-1 rounded-md">+{phone}</p>
        </div>
      )}

      {status === "error" && (
        <div className="text-center">
          <p className="text-destructive mb-4 font-medium">Failed to connect to WhatsApp API.</p>
          <Button variant="outline" onClick={initSession}>Retry</Button>
        </div>
      )}
    </div>
  );
}
