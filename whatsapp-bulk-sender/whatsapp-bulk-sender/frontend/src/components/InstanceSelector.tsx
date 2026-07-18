"use client";

import { useState, useEffect } from "react";
import { useInstance } from "@/context/InstanceContext";
import { getInstances, createInstance, deleteInstance, getConnectionState } from "@/lib/api-client";
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select";
import { Button } from "@/components/ui/button";
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog";
import { Input } from "@/components/ui/input";
import { toast } from "sonner";
import { Plus, Trash2, Smartphone, Loader2 } from "lucide-react";
import Image from "next/image";

export function InstanceSelector() {
  const { selectedInstance, setSelectedInstance } = useInstance();
  const [instances, setInstances] = useState<any[]>([]);
  const [loading, setLoading] = useState(true);
  const [isModalOpen, setIsModalOpen] = useState(false);
  const [newInstanceName, setNewInstanceName] = useState("");
  const [qrCode, setQrCode] = useState<string | null>(null);
  const [isCreating, setIsCreating] = useState(false);
  const [connectionStatus, setConnectionStatus] = useState<string>("connecting");

  const loadInstances = async () => {
    try {
      const data = await getInstances();
      setInstances(data.instances || []);
    } catch (err) {
      console.error("Failed to load instances:", err);
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => {
    loadInstances();
  }, []);

  const handleCreateInstance = async () => {
    if (!newInstanceName.trim()) {
      toast.error("Please enter a name for the new connection");
      return;
    }

    setIsCreating(true);
    setQrCode(null);
    setConnectionStatus("connecting");

    try {
      const res = await createInstance(newInstanceName.trim());
      if (res.result?.qrcode?.base64) {
        setQrCode(res.result.qrcode.base64);
        pollConnectionStatus(newInstanceName.trim());
      } else {
        toast.error("Failed to get QR code. Please try again.");
      }
    } catch (err) {
      toast.error("Failed to create instance. Name might already exist.");
    } finally {
      setIsCreating(false);
    }
  };

  const pollConnectionStatus = async (name: string) => {
    const interval = setInterval(async () => {
      try {
        const state = await getConnectionState(name);
        const status = state?.instance?.state || state?.state || "connecting";
        setConnectionStatus(status);

        if (status === "open") {
          clearInterval(interval);
          toast.success("Successfully connected!");
          setIsModalOpen(false);
          setNewInstanceName("");
          setQrCode(null);
          await loadInstances();
          setSelectedInstance(name);
        }
      } catch (e) {
        // Ignore errors during polling
      }
    }, 3000);

    // Clear interval when modal closes
    const checkModalOpen = setInterval(() => {
      if (!isModalOpen) {
        clearInterval(interval);
        clearInterval(checkModalOpen);
      }
    }, 1000);
  };

  const handleDelete = async (e: React.MouseEvent, name: string) => {
    e.stopPropagation();
    if (!confirm(`Are you sure you want to disconnect ${name}?`)) return;

    try {
      await deleteInstance(name);
      toast.success("Instance deleted");
      if (selectedInstance === name) {
        setSelectedInstance("bulk-sender-main");
      }
      loadInstances();
    } catch (err) {
      toast.error("Failed to delete instance");
    }
  };

  if (loading) {
    return <div className="h-10 w-48 bg-muted animate-pulse rounded-md"></div>;
  }

  // Ensure default instance exists in UI even if API fails or it's new
  const displayInstances = instances.some(i => i.name === selectedInstance || i.instance?.instanceName === selectedInstance)
    ? instances
    : [...instances, { name: selectedInstance, connectionStatus: "unknown" }];

  return (
    <div className="flex items-center gap-2">
      <Select value={selectedInstance} onValueChange={(val) => val && setSelectedInstance(val)}>
        <SelectTrigger className="w-[200px] bg-slate-900 border-slate-700">
          <Smartphone className="w-4 h-4 mr-2 text-slate-400" />
          <SelectValue placeholder="Select Number" />
        </SelectTrigger>
        <SelectContent className="bg-slate-900 border-slate-700">
          {displayInstances.map((inst, i) => {
            const name = inst.name || inst.instance?.instanceName || `Instance ${i}`;
            const status = inst.connectionStatus || inst.instance?.status || "unknown";
            
            return (
              <SelectItem key={name} value={name} className="focus:bg-slate-800">
                <div className="flex items-center justify-between w-full gap-2">
                  <div className="flex flex-col">
                    <span className="font-medium">{name}</span>
                    <span className={`text-[10px] uppercase tracking-wider ${status === "open" ? "text-emerald-400" : "text-amber-400"}`}>
                      {status}
                    </span>
                  </div>
                  {name !== "bulk-sender-main" && (
                    <div 
                      role="button"
                      className="p-1 hover:bg-red-500/20 rounded text-red-400"
                      onClick={(e) => handleDelete(e, name)}
                    >
                      <Trash2 className="w-3 h-3" />
                    </div>
                  )}
                </div>
              </SelectItem>
            );
          })}
        </SelectContent>
      </Select>

      <Button 
        variant="outline" 
        size="icon" 
        className="bg-slate-900 border-slate-700 hover:bg-slate-800"
        onClick={() => setIsModalOpen(true)}
      >
        <Plus className="w-4 h-4" />
      </Button>

      <Dialog open={isModalOpen} onOpenChange={setIsModalOpen}>
        <DialogContent className="bg-slate-900 border-slate-700 text-white sm:max-w-md">
          <DialogHeader>
            <DialogTitle>Connect New WhatsApp Number</DialogTitle>
            <DialogDescription className="text-slate-400">
              Give this connection a name, then scan the QR code with your WhatsApp app.
            </DialogDescription>
          </DialogHeader>

          {!qrCode ? (
            <div className="flex flex-col gap-4 py-4">
              <Input
                placeholder="e.g. sales-team-1"
                value={newInstanceName}
                onChange={(e) => setNewInstanceName(e.target.value.replace(/[^a-zA-Z0-9-]/g, ''))}
                className="bg-slate-800 border-slate-700"
              />
              <Button 
                onClick={handleCreateInstance} 
                disabled={isCreating || !newInstanceName}
                className="w-full bg-blue-600 hover:bg-blue-700"
              >
                {isCreating ? <Loader2 className="w-4 h-4 mr-2 animate-spin" /> : "Generate QR Code"}
              </Button>
            </div>
          ) : (
            <div className="flex flex-col items-center gap-4 py-4">
              <div className="bg-white p-4 rounded-xl shadow-lg">
                {qrCode.includes("base64") ? (
                  <Image src={qrCode} alt="WhatsApp QR Code" width={256} height={256} className="rounded-lg" />
                ) : (
                  <div className="w-64 h-64 bg-slate-100 flex items-center justify-center text-slate-500 rounded-lg">
                    Invalid QR Data
                  </div>
                )}
              </div>
              <div className="text-center">
                <p className="font-medium text-emerald-400 animate-pulse flex items-center justify-center gap-2">
                  <Loader2 className="w-4 h-4 animate-spin" />
                  Waiting for scan...
                </p>
                <p className="text-sm text-slate-400 mt-2">
                  Open WhatsApp {'>'} Linked Devices {'>'} Link a Device
                </p>
              </div>
            </div>
          )}
        </DialogContent>
      </Dialog>
    </div>
  );
}
