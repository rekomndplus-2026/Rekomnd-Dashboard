"use client";

import { useState, useEffect, useCallback, useRef } from "react";
import { toast } from "sonner";
import {
  getGroups,
  subscribeToGroups,
  getMonitorStatus,
  getLeads,
  deleteLead,
  exportLeads,
  exportGroupMembers,
} from "@/lib/api-client";
import { LeadScoreBadge } from "@/components/dashboard/LeadScoreBadge";
import {
  Users,
  Radio,
  Download,
  Trash2,
  Search,
  RefreshCw,
  Filter,
  Building2,
  Phone,
  MessageSquare,
  Clock,
  ChevronLeft,
  ChevronRight,
  AlertCircle,
  CheckCircle2,
  Loader2,
  UserCheck,
  FileSpreadsheet,
  Wifi,
  WifiOff,
  X,
} from "lucide-react";
import Link from "next/link";
import { useInstance } from "@/context/InstanceContext";
import { InstanceSelector } from "@/components/InstanceSelector";

// ─── Types ────────────────────────────────────────────────────

interface Group {
  group_id: string;
  name: string;
  participant_count: number;
  description?: string;
}

interface Lead {
  lead_id: string;
  phone: string;
  name?: string;
  message: string;
  score: number;
  lead_tier: string;
  matched_keywords: string[];
  group_id: string;
  group_name?: string;
  timestamp: string;
  instance_name: string;
}

// ─── Helpers ──────────────────────────────────────────────────

function formatTime(iso: string) {
  try {
    const d = new Date(iso);
    return d.toLocaleString("en-US", {
      month: "short",
      day: "numeric",
      hour: "2-digit",
      minute: "2-digit",
    });
  } catch {
    return iso;
  }
}

// ─── Sub-components ───────────────────────────────────────────

function StatCard({
  icon,
  label,
  value,
  color,
}: {
  icon: React.ReactNode;
  label: string;
  value: string | number;
  color: string;
}) {
  return (
    <div className="bg-card/40 backdrop-blur-md border border-border/40 rounded-2xl p-5 flex items-center gap-4">
      <div className={`w-12 h-12 rounded-xl flex items-center justify-center ${color}`}>
        {icon}
      </div>
      <div>
        <p className="text-2xl font-black text-white">{value}</p>
        <p className="text-sm text-muted-foreground">{label}</p>
      </div>
    </div>
  );
}

// ─── Main Page ────────────────────────────────────────────────

export default function MonitorPage() {
  const [groups, setGroups] = useState<Group[]>([]);
  const [selectedGroups, setSelectedGroups] = useState<Set<string>>(new Set());
  const [leads, setLeads] = useState<Lead[]>([]);
  const [totalLeads, setTotalLeads] = useState(0);
  const [page, setPage] = useState(1);
  const [totalPages, setTotalPages] = useState(1);
  const [isMonitoring, setIsMonitoring] = useState(false);
  const [loadingGroups, setLoadingGroups] = useState(false);
  const [loadingLeads, setLoadingLeads] = useState(false);
  const [subscribing, setSubscribing] = useState(false);
  const [exportingLeads, setExportingLeads] = useState(false);
  const [exportingMembers, setExportingMembers] = useState<string | null>(null);
  const [deletingId, setDeletingId] = useState<string | null>(null);
  const [search, setSearch] = useState("");
  const [tierFilter, setTierFilter] = useState<string>("");
  const [groupFilter, setGroupFilter] = useState<string>("");
  const [activeTab, setActiveTab] = useState<"groups" | "leads">("groups");
  const [isCached, setIsCached] = useState(false);
  const pollRef = useRef<NodeJS.Timeout | null>(null);

  const API_BASE_URL = process.env.NEXT_PUBLIC_BACKEND_URL || "http://localhost:8000";

  const { selectedInstance } = useInstance();
  const [groupsError, setGroupsError] = useState<string | null>(null);

  // ── Load groups (forceRefresh=true bypasses Redis cache, takes ~75s)
  const loadGroups = useCallback(async (forceRefresh = false) => {
    setLoadingGroups(true);
    setGroupsError(null);
    try {
      const data = await getGroups(selectedInstance, forceRefresh);
      setGroups(data.groups || []);
      setIsCached(data.cached === true);
    } catch (e: any) {
      const msg = e.message || "Unknown error";
      setGroupsError(msg);
      toast.error(`Could not fetch groups: ${msg}`);
    } finally {
      setLoadingGroups(false);
    }
  }, []);

  // ── Load leads
  const loadLeads = useCallback(async () => {
    setLoadingLeads(true);
    try {
      const data = await getLeads({
        page,
        page_size: 20,
        search: search || undefined,
        tier: tierFilter || undefined,
        group_id: groupFilter || undefined,
      });
      setLeads(data.leads || []);
      setTotalLeads(data.total || 0);
      setTotalPages(data.total_pages || 1);
    } catch (e: any) {
      // Silently fail on poll errors
    } finally {
      setLoadingLeads(false);
    }
  }, [page, search, tierFilter, groupFilter]);

  // ── Load monitor status
  const loadStatus = useCallback(async () => {
    try {
      const data = await getMonitorStatus(selectedInstance);
      setIsMonitoring(data.is_active || false);
      if (data.monitored_groups?.length > 0) {
        setSelectedGroups(new Set(data.monitored_groups));
      }
    } catch {}
  }, [selectedInstance]);

  // Load groups on mount and when selectedInstance changes
  useEffect(() => {
    loadGroups();
    loadStatus();
  }, [loadGroups, loadStatus]);

  useEffect(() => {
    loadLeads();
  }, [loadLeads]);

  // ── Auto-poll leads every 10s when monitoring
  useEffect(() => {
    if (isMonitoring) {
      pollRef.current = setInterval(loadLeads, 10000);
    } else {
      if (pollRef.current) clearInterval(pollRef.current);
    }
    return () => {
      if (pollRef.current) clearInterval(pollRef.current);
    };
  }, [isMonitoring, loadLeads]);

  // ── Subscribe / start monitoring
  const handleStartMonitoring = async () => {
    if (selectedGroups.size === 0) {
      toast.error("Please select at least one group to monitor.");
      return;
    }
    setSubscribing(true);
    try {
      const webhookUrl = `${API_BASE_URL}/api/monitor/webhook`;
      await subscribeToGroups({
        group_ids: Array.from(selectedGroups),
        instance_name: selectedInstance,
        webhook_url: webhookUrl,
      });
      setIsMonitoring(true);
      setActiveTab("leads");
      toast.success(`Monitoring ${selectedGroups.size} group(s). Leads will appear automatically.`);
    } catch (e: any) {
      toast.error(e.message || "Failed to start monitoring");
    } finally {
      setSubscribing(false);
    }
  };

  // ── Stop monitoring
  const handleStopMonitoring = async () => {
    try {
      await subscribeToGroups({ group_ids: [], instance_name: selectedInstance });
      setIsMonitoring(false);
      toast.info("Monitoring stopped.");
    } catch {}
  };

  // ── Delete lead
  const handleDeleteLead = async (leadId: string) => {
    setDeletingId(leadId);
    try {
      await deleteLead(leadId);
      setLeads((prev) => prev.filter((l) => l.lead_id !== leadId));
      setTotalLeads((prev) => prev - 1);
      toast.success("Lead removed.");
    } catch {
      toast.error("Failed to delete lead.");
    } finally {
      setDeletingId(null);
    }
  };

  // ── Export leads
  const handleExportLeads = async () => {
    setExportingLeads(true);
    try {
      await exportLeads({
        instance_name: selectedInstance,
        group_id: groupFilter || undefined,
        tier: tierFilter || undefined,
      });
      toast.success("Leads exported successfully!");
    } catch {
      toast.error("Export failed.");
    } finally {
      setExportingLeads(false);
    }
  };

  // ── Export group members
  const handleExportGroupMembers = async (groupId: string, groupName: string) => {
    setExportingMembers(groupId);
    try {
      await exportGroupMembers(selectedInstance, groupId, groupName);
      toast.success("Group members exported!");
    } catch {
      toast.error("Failed to export group members.");
    } finally {
      setExportingMembers(null);
    }
  };

  const toggleGroup = (groupId: string) => {
    setSelectedGroups((prev) => {
      const next = new Set(prev);
      if (next.has(groupId)) next.delete(groupId);
      else next.add(groupId);
      return next;
    });
  };

  const hotLeads = leads.filter((l) => l.lead_tier === "hot").length;
  const warmLeads = leads.filter((l) => l.lead_tier === "warm").length;

  // ── Render ────────────────────────────────────────────────

  return (
    <main className="min-h-screen bg-background text-foreground relative overflow-hidden font-sans">
      {/* Background blobs */}
      <div className="absolute top-[-20%] left-[-10%] w-[50%] h-[50%] bg-primary/10 blur-[120px] rounded-full pointer-events-none" />
      <div className="absolute bottom-[-20%] right-[-10%] w-[40%] h-[40%] bg-violet-500/5 blur-[120px] rounded-full pointer-events-none" />

      {/* Clean Navbar (Removed Logo for iframe) */}
      <nav className="w-full bg-background/50 backdrop-blur-md sticky top-0 z-50">
        <div className="max-w-7xl mx-auto px-6 h-16 flex items-center justify-end">
          <div className="flex items-center gap-4">
            <InstanceSelector />
            <Link
              href="/"
              className="px-4 py-2 rounded-xl text-sm text-muted-foreground hover:text-white hover:bg-white/5 transition-colors"
            >
              Bulk Sender
            </Link>
            <div className="px-4 py-2 rounded-xl text-sm text-primary bg-primary/10 border border-primary/20 font-semibold flex items-center gap-2">
              <Radio className="w-4 h-4" />
              Group Monitor
            </div>
          </div>
        </div>
      </nav>

      <div className="max-w-7xl mx-auto p-6 lg:py-10 relative z-10">
        {/* Header */}
        <header className="mb-8">
          <div className="flex items-start justify-between flex-wrap gap-4">
            <div>
              <h1 className="text-4xl lg:text-5xl font-black tracking-tight mb-3 text-white">
                Group Monitor
              </h1>
              <p className="text-lg text-muted-foreground max-w-2xl">
                Automatically detect real estate buyer leads from WhatsApp groups using AI-powered message classification.
              </p>
            </div>
            {/* Status pill */}
            <div
              className={`flex items-center gap-2 px-5 py-3 rounded-2xl border font-semibold text-sm ${
                isMonitoring
                  ? "bg-emerald-500/10 border-emerald-500/30 text-emerald-400"
                  : "bg-zinc-800/40 border-zinc-700/40 text-zinc-400"
              }`}
            >
              {isMonitoring ? (
                <>
                  <span className="relative flex h-2.5 w-2.5">
                    <span className="animate-ping absolute inline-flex h-full w-full rounded-full bg-emerald-400 opacity-75"></span>
                    <span className="relative inline-flex rounded-full h-2.5 w-2.5 bg-emerald-500"></span>
                  </span>
                  Monitoring {selectedGroups.size} group(s)
                </>
              ) : (
                <>
                  <WifiOff className="w-4 h-4" />
                  Not monitoring
                </>
              )}
            </div>
          </div>
        </header>

        {/* Stats row */}
        <div className="grid grid-cols-2 lg:grid-cols-4 gap-4 mb-8">
          <StatCard
            icon={<MessageSquare className="w-6 h-6" />}
            label="Total Leads"
            value={totalLeads}
            color="bg-primary/20 text-primary"
          />
          <StatCard
            icon={<span className="text-xl">🔥</span>}
            label="Hot Leads"
            value={hotLeads}
            color="bg-red-500/20 text-red-400"
          />
          <StatCard
            icon={<span className="text-xl">⚡</span>}
            label="Warm Leads"
            value={warmLeads}
            color="bg-amber-500/20 text-amber-400"
          />
          <StatCard
            icon={<Users className="w-6 h-6" />}
            label="Groups Watched"
            value={selectedGroups.size}
            color="bg-violet-500/20 text-violet-400"
          />
        </div>

        {/* Tabs */}
        <div className="flex gap-2 mb-6 border-b border-border/30 pb-4">
          <button
            id="tab-groups"
            onClick={() => setActiveTab("groups")}
            className={`flex items-center gap-2 px-5 py-2.5 rounded-xl text-sm font-semibold transition-all ${
              activeTab === "groups"
                ? "bg-primary text-primary-foreground shadow-lg shadow-primary/20"
                : "text-muted-foreground hover:text-white hover:bg-white/5"
            }`}
          >
            <Users className="w-4 h-4" />
            Groups
          </button>
          <button
            id="tab-leads"
            onClick={() => setActiveTab("leads")}
            className={`flex items-center gap-2 px-5 py-2.5 rounded-xl text-sm font-semibold transition-all ${
              activeTab === "leads"
                ? "bg-primary text-primary-foreground shadow-lg shadow-primary/20"
                : "text-muted-foreground hover:text-white hover:bg-white/5"
            }`}
          >
            <Building2 className="w-4 h-4" />
            Leads Dashboard
            {totalLeads > 0 && (
              <span className="bg-primary/30 text-primary text-xs px-2 py-0.5 rounded-full font-bold">
                {totalLeads}
              </span>
            )}
          </button>
        </div>

        {/* ─── GROUPS TAB ───────────────────────────────────── */}
        {activeTab === "groups" && (
          <div className="space-y-6 animate-in fade-in duration-300">
            {/* Control bar */}
            <div className="flex items-center justify-between flex-wrap gap-3">
              <div className="flex items-center gap-3 flex-wrap">
                <p className="text-muted-foreground text-sm">
                  Select groups to monitor. Incoming messages will be auto-classified.
                </p>
                {isCached && !loadingGroups && (
                  <span className="flex items-center gap-1 text-xs text-amber-400/80 bg-amber-500/10 border border-amber-500/20 px-2.5 py-1 rounded-lg whitespace-nowrap">
                    ⚡ Cached — click Live Refresh to reload
                  </span>
                )}
              </div>
              <div className="flex gap-3">
                <button
                  id="btn-refresh-groups"
                  onClick={() => loadGroups(true)}
                  disabled={loadingGroups}
                  title="Fetch live data from WhatsApp (takes ~60–80s)"
                  className="flex items-center gap-2 px-4 py-2 rounded-xl border border-border/40 bg-card/40 backdrop-blur-sm text-sm text-muted-foreground hover:text-white hover:border-primary/40 transition-all disabled:opacity-40"
                >
                  <RefreshCw className={`w-4 h-4 ${loadingGroups ? "animate-spin" : ""}`} />
                  {loadingGroups ? "Fetching..." : "Live Refresh"}
                </button>

                {isMonitoring ? (
                  <button
                    id="btn-stop-monitoring"
                    onClick={handleStopMonitoring}
                    className="flex items-center gap-2 px-5 py-2 rounded-xl bg-red-500/20 border border-red-500/30 text-red-400 text-sm font-semibold hover:bg-red-500/30 transition-all"
                  >
                    <WifiOff className="w-4 h-4" />
                    Stop Monitoring
                  </button>
                ) : (
                  <button
                    id="btn-start-monitoring"
                    onClick={handleStartMonitoring}
                    disabled={subscribing || selectedGroups.size === 0}
                    className="flex items-center gap-2 px-6 py-2 rounded-xl bg-primary text-primary-foreground text-sm font-semibold hover:opacity-90 transition-all disabled:opacity-40 disabled:cursor-not-allowed shadow-lg shadow-primary/20"
                  >
                    {subscribing ? (
                      <Loader2 className="w-4 h-4 animate-spin" />
                    ) : (
                      <Radio className="w-4 h-4" />
                    )}
                    Start Monitoring ({selectedGroups.size})
                  </button>
                )}
              </div>
            </div>

            {/* Groups grid */}
            {loadingGroups ? (
              <div className="flex flex-col items-center justify-center h-64 gap-4">
                <Loader2 className="w-10 h-10 text-primary animate-spin" />
                <div className="text-center">
                    Group fetch started in the background. Check logs for details.<br/>
                    <span className="text-sm opacity-80 mt-2 inline-block">
                    This can take a moment depending on the number of groups
                    </span>

                </div>
              </div>
            ) : groups.length === 0 ? (
              <div className="flex flex-col items-center justify-center h-64 gap-4 border-2 border-dashed border-border/30 rounded-3xl p-8">
                <Users className="w-12 h-12 text-muted-foreground/30" />
                <div className="text-center">
                  <p className="text-muted-foreground font-semibold">
                    {groupsError ? "Failed to load groups" : "No groups found"}
                  </p>
                  {groupsError ? (
                    <p className="text-red-400/70 text-sm mt-1 max-w-sm font-mono bg-red-500/5 border border-red-500/20 rounded-lg px-3 py-2">
                      {groupsError}
                    </p>
                  ) : (
                    <p className="text-muted-foreground/50 text-sm mt-1">
                      Make sure WhatsApp is connected and you are in at least one group.
                    </p>
                  )}
                  <a
                    href={`${API_BASE_URL}/api/monitor/groups/debug`}
                    target="_blank"
                    rel="noopener noreferrer"
                    className="inline-block mt-3 text-xs text-primary/60 hover:text-primary underline transition-colors"
                  >
                    🔍 View raw Gateway response →
                  </a>
                </div>
                <button
                  onClick={() => loadGroups(true)}
                  className="mt-2 px-4 py-2 rounded-xl bg-primary/20 border border-primary/30 text-primary text-sm font-semibold hover:bg-primary/30 transition-all"
                >
                  Retry Live Fetch
                </button>
              </div>
            ) : (
              <div className="grid grid-cols-1 md:grid-cols-2 xl:grid-cols-3 gap-4">
                {groups.map((group) => {
                  const selected = selectedGroups.has(group.group_id);
                  return (
                    <div
                      key={group.group_id}
                      className={`
                        relative bg-card/40 backdrop-blur-md border rounded-2xl p-5 cursor-pointer
                        transition-all duration-200 hover:scale-[1.01] group
                        ${selected
                          ? "border-primary/60 bg-primary/5 shadow-lg shadow-primary/10"
                          : "border-border/40 hover:border-border/70"
                        }
                      `}
                      onClick={() => toggleGroup(group.group_id)}
                    >
                      {/* Selection indicator */}
                      <div
                        className={`absolute top-4 right-4 w-5 h-5 rounded-full border-2 flex items-center justify-center transition-all ${
                          selected
                            ? "bg-primary border-primary"
                            : "border-border/60 group-hover:border-primary/50"
                        }`}
                      >
                        {selected && (
                          <svg className="w-3 h-3 text-white" fill="currentColor" viewBox="0 0 20 20">
                            <path fillRule="evenodd" d="M16.707 5.293a1 1 0 010 1.414l-8 8a1 1 0 01-1.414 0l-4-4a1 1 0 011.414-1.414L8 12.586l7.293-7.293a1 1 0 011.414 0z" clipRule="evenodd" />
                          </svg>
                        )}
                      </div>

                      <div className="flex items-start gap-3 pr-8">
                        {/* Group icon */}
                        <div className="w-11 h-11 rounded-xl bg-gradient-to-br from-primary/20 to-violet-500/20 border border-primary/20 flex items-center justify-center shrink-0">
                          <Users className="w-5 h-5 text-primary" />
                        </div>
                        <div className="min-w-0">
                          <p className="font-bold text-white truncate">{group.name}</p>
                          <p className="text-xs text-muted-foreground mt-0.5 truncate">
                            {group.group_id}
                          </p>
                          <div className="flex items-center gap-2 mt-2">
                            <span className="flex items-center gap-1 text-xs text-muted-foreground">
                              <UserCheck className="w-3 h-3" />
                              {group.participant_count} members
                            </span>
                          </div>
                        </div>
                      </div>

                      {/* Export members button */}
                      <button
                        id={`btn-export-members-${group.group_id}`}
                        onClick={(e) => {
                          e.stopPropagation();
                          handleExportGroupMembers(group.group_id, group.name);
                        }}
                        disabled={exportingMembers === group.group_id}
                        className="mt-4 w-full flex items-center justify-center gap-2 px-3 py-2 rounded-xl bg-emerald-500/10 border border-emerald-500/20 text-emerald-400 text-xs font-semibold hover:bg-emerald-500/20 transition-all disabled:opacity-50"
                        title="Export all phone numbers in this group"
                      >
                        {exportingMembers === group.group_id ? (
                          <Loader2 className="w-3.5 h-3.5 animate-spin" />
                        ) : (
                          <FileSpreadsheet className="w-3.5 h-3.5" />
                        )}
                        Export All Numbers (.xlsx)
                      </button>
                    </div>
                  );
                })}
              </div>
            )}

            {/* Legend */}
            <div className="bg-card/20 border border-border/30 rounded-2xl p-5">
              <h3 className="text-sm font-bold text-white mb-3 flex items-center gap-2">
                <AlertCircle className="w-4 h-4 text-primary" />
                Lead Score System
              </h3>
              <div className="grid grid-cols-1 sm:grid-cols-3 gap-4 text-sm">
                <div className="flex items-center gap-3">
                  <div className="w-8 h-8 rounded-full bg-red-500/20 border border-red-500/40 flex items-center justify-center text-red-400 font-black text-xs">7+</div>
                  <div>
                    <p className="text-red-400 font-semibold">🔥 HOT Lead</p>
                    <p className="text-muted-foreground text-xs">Strong buying intent</p>
                  </div>
                </div>
                <div className="flex items-center gap-3">
                  <div className="w-8 h-8 rounded-full bg-amber-500/20 border border-amber-500/40 flex items-center justify-center text-amber-400 font-black text-xs">3-6</div>
                  <div>
                    <p className="text-amber-400 font-semibold">⚡ WARM Lead</p>
                    <p className="text-muted-foreground text-xs">Moderate intent signals</p>
                  </div>
                </div>
                <div className="flex items-center gap-3">
                  <div className="w-8 h-8 rounded-full bg-zinc-700/40 border border-zinc-600/40 flex items-center justify-center text-zinc-400 font-black text-xs">&lt;3</div>
                  <div>
                    <p className="text-zinc-400 font-semibold">○ Not a lead</p>
                    <p className="text-muted-foreground text-xs">General chatter</p>
                  </div>
                </div>
              </div>
            </div>
          </div>
        )}

        {/* ─── LEADS TAB ────────────────────────────────────── */}
        {activeTab === "leads" && (
          <div className="space-y-5 animate-in fade-in duration-300">
            {/* Toolbar */}
            <div className="flex flex-wrap items-center gap-3">
              {/* Search */}
              <div className="relative flex-1 min-w-[240px]">
                <Search className="absolute left-3 top-1/2 -translate-y-1/2 w-4 h-4 text-muted-foreground" />
                <input
                  id="leads-search"
                  type="text"
                  placeholder="Search by name, phone, or message..."
                  value={search}
                  onChange={(e) => { setSearch(e.target.value); setPage(1); }}
                  className="w-full pl-10 pr-4 py-2.5 bg-card/40 border border-border/40 rounded-xl text-sm text-white placeholder:text-muted-foreground focus:outline-none focus:border-primary/50 focus:ring-1 focus:ring-primary/20 transition-all"
                />
                {search && (
                  <button onClick={() => setSearch("")} className="absolute right-3 top-1/2 -translate-y-1/2 text-muted-foreground hover:text-white">
                    <X className="w-3.5 h-3.5" />
                  </button>
                )}
              </div>

              {/* Tier filter */}
              <select
                id="filter-tier"
                value={tierFilter}
                onChange={(e) => { setTierFilter(e.target.value); setPage(1); }}
                className="px-3 py-2.5 bg-card/40 border border-border/40 rounded-xl text-sm text-white focus:outline-none focus:border-primary/50 transition-all"
              >
                <option value="">All Tiers</option>
                <option value="hot">🔥 Hot</option>
                <option value="warm">⚡ Warm</option>
              </select>

              {/* Group filter */}
              <select
                id="filter-group"
                value={groupFilter}
                onChange={(e) => { setGroupFilter(e.target.value); setPage(1); }}
                className="px-3 py-2.5 bg-card/40 border border-border/40 rounded-xl text-sm text-white focus:outline-none focus:border-primary/50 transition-all max-w-[200px]"
              >
                <option value="">All Groups</option>
                {groups.map((g) => (
                  <option key={g.group_id} value={g.group_id}>{g.name}</option>
                ))}
              </select>

              <div className="flex gap-2 ml-auto">
                <button
                  id="btn-refresh-leads"
                  onClick={loadLeads}
                  disabled={loadingLeads}
                  className="flex items-center gap-2 px-4 py-2.5 rounded-xl border border-border/40 bg-card/40 text-sm text-muted-foreground hover:text-white hover:border-primary/40 transition-all"
                >
                  <RefreshCw className={`w-4 h-4 ${loadingLeads ? "animate-spin" : ""}`} />
                </button>

                <button
                  id="btn-export-leads"
                  onClick={handleExportLeads}
                  disabled={exportingLeads || totalLeads === 0}
                  className="flex items-center gap-2 px-5 py-2.5 rounded-xl bg-emerald-600 text-white text-sm font-semibold hover:bg-emerald-500 transition-all disabled:opacity-40 disabled:cursor-not-allowed shadow-lg shadow-emerald-900/30"
                >
                  {exportingLeads ? (
                    <Loader2 className="w-4 h-4 animate-spin" />
                  ) : (
                    <Download className="w-4 h-4" />
                  )}
                  Export Excel
                </button>
              </div>
            </div>

            {/* Leads table */}
            {loadingLeads && leads.length === 0 ? (
              <div className="flex flex-col items-center justify-center h-64 gap-4">
                <Loader2 className="w-10 h-10 text-primary animate-spin" />
                <p className="text-muted-foreground text-sm">Loading leads...</p>
              </div>
            ) : leads.length === 0 ? (
              <div className="flex flex-col items-center justify-center h-64 gap-4 border-2 border-dashed border-border/30 rounded-3xl">
                <Building2 className="w-14 h-14 text-muted-foreground/20" />
                <div className="text-center">
                  <p className="text-white font-semibold text-lg">No leads yet</p>
                  <p className="text-muted-foreground/60 text-sm mt-1 max-w-sm">
                    {isMonitoring
                      ? "Monitoring is active. Leads will appear here as people send messages in your groups."
                      : "Select groups and start monitoring to detect buyer leads automatically."}
                  </p>
                </div>
                {!isMonitoring && (
                  <button
                    onClick={() => setActiveTab("groups")}
                    className="px-5 py-2.5 rounded-xl bg-primary/20 border border-primary/30 text-primary text-sm font-semibold hover:bg-primary/30 transition-all"
                  >
                    Go to Groups →
                  </button>
                )}
              </div>
            ) : (
              <>
                <div className="bg-card/30 backdrop-blur-md border border-border/30 rounded-2xl overflow-hidden">
                  <div className="overflow-x-auto">
                    <table className="w-full text-sm">
                      <thead>
                        <tr className="border-b border-border/30 bg-card/50">
                          <th className="text-left px-5 py-4 text-muted-foreground font-semibold text-xs uppercase tracking-wider">Contact</th>
                          <th className="text-left px-5 py-4 text-muted-foreground font-semibold text-xs uppercase tracking-wider">Score</th>
                          <th className="text-left px-5 py-4 text-muted-foreground font-semibold text-xs uppercase tracking-wider">Message</th>
                          <th className="text-left px-5 py-4 text-muted-foreground font-semibold text-xs uppercase tracking-wider">Group</th>
                          <th className="text-left px-5 py-4 text-muted-foreground font-semibold text-xs uppercase tracking-wider">Time</th>
                          <th className="px-5 py-4"></th>
                        </tr>
                      </thead>
                      <tbody className="divide-y divide-border/20">
                        {leads.map((lead) => (
                          <tr
                            key={lead.lead_id}
                            className="hover:bg-white/[0.02] transition-colors group"
                          >
                            {/* Contact */}
                            <td className="px-5 py-4">
                              <div className="flex items-center gap-3">
                                <div className="w-9 h-9 rounded-full bg-gradient-to-br from-primary/20 to-violet-500/20 border border-primary/20 flex items-center justify-center text-primary font-bold text-xs shrink-0">
                                  {(lead.name || lead.phone)?.[0]?.toUpperCase() || "?"}
                                </div>
                                <div>
                                  <p className="font-semibold text-white text-sm">
                                    {lead.name || "Unknown"}
                                  </p>
                                  <p className="text-xs text-muted-foreground flex items-center gap-1 mt-0.5">
                                    <Phone className="w-3 h-3" />
                                    {lead.phone}
                                  </p>
                                </div>
                              </div>
                            </td>

                            {/* Score */}
                            <td className="px-5 py-4">
                              <LeadScoreBadge score={lead.score} tier={lead.lead_tier} size="sm" />
                              {lead.matched_keywords.length > 0 && (
                                <div className="flex flex-wrap gap-1 mt-2 max-w-[160px]">
                                  {lead.matched_keywords.slice(0, 2).map((kw) => (
                                    <span key={kw} className="text-[10px] bg-primary/10 text-primary/80 px-1.5 py-0.5 rounded-md border border-primary/10">
                                      {kw}
                                    </span>
                                  ))}
                                  {lead.matched_keywords.length > 2 && (
                                    <span className="text-[10px] text-muted-foreground">+{lead.matched_keywords.length - 2}</span>
                                  )}
                                </div>
                              )}
                            </td>

                            {/* Message */}
                            <td className="px-5 py-4 max-w-xs">
                              <p className="text-white/80 text-sm line-clamp-2 leading-relaxed">
                                {lead.message}
                              </p>
                            </td>

                            {/* Group */}
                            <td className="px-5 py-4">
                              <span className="flex items-center gap-1.5 text-xs text-muted-foreground bg-card/50 border border-border/30 px-2.5 py-1 rounded-lg w-fit">
                                <Users className="w-3 h-3" />
                                {lead.group_name || lead.group_id}
                              </span>
                            </td>

                            {/* Time */}
                            <td className="px-5 py-4">
                              <span className="text-xs text-muted-foreground flex items-center gap-1 whitespace-nowrap">
                                <Clock className="w-3 h-3" />
                                {formatTime(lead.timestamp)}
                              </span>
                            </td>

                            {/* Actions */}
                            <td className="px-5 py-4">
                              <button
                                id={`btn-delete-lead-${lead.lead_id}`}
                                onClick={() => handleDeleteLead(lead.lead_id)}
                                disabled={deletingId === lead.lead_id}
                                className="opacity-0 group-hover:opacity-100 transition-all w-8 h-8 flex items-center justify-center rounded-lg hover:bg-red-500/20 text-muted-foreground hover:text-red-400"
                                title="Delete lead"
                              >
                                {deletingId === lead.lead_id ? (
                                  <Loader2 className="w-4 h-4 animate-spin" />
                                ) : (
                                  <Trash2 className="w-4 h-4" />
                                )}
                              </button>
                            </td>
                          </tr>
                        ))}
                      </tbody>
                    </table>
                  </div>
                </div>

                {/* Pagination */}
                {totalPages > 1 && (
                  <div className="flex items-center justify-between">
                    <p className="text-sm text-muted-foreground">
                      Showing {leads.length} of {totalLeads} leads
                    </p>
                    <div className="flex items-center gap-2">
                      <button
                        id="btn-prev-page"
                        onClick={() => setPage((p) => Math.max(1, p - 1))}
                        disabled={page === 1}
                        className="w-9 h-9 flex items-center justify-center rounded-xl border border-border/40 bg-card/40 text-muted-foreground hover:text-white hover:border-primary/40 disabled:opacity-30 transition-all"
                      >
                        <ChevronLeft className="w-4 h-4" />
                      </button>
                      <span className="text-sm text-muted-foreground px-2">
                        Page {page} of {totalPages}
                      </span>
                      <button
                        id="btn-next-page"
                        onClick={() => setPage((p) => Math.min(totalPages, p + 1))}
                        disabled={page === totalPages}
                        className="w-9 h-9 flex items-center justify-center rounded-xl border border-border/40 bg-card/40 text-muted-foreground hover:text-white hover:border-primary/40 disabled:opacity-30 transition-all"
                      >
                        <ChevronRight className="w-4 h-4" />
                      </button>
                    </div>
                  </div>
                )}
              </>
            )}
          </div>
        )}
      </div>
    </main>
  );
}
