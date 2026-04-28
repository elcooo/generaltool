import {
  ArrowRight,
  Crosshair,
  Crown,
  DoorOpen,
  Flag,
  Hammer,
  Hash,
  LogIn,
  LogOut,
  MapPin,
  Octagon,
  Package,
  Pause,
  Play,
  Repeat,
  Shield,
  Sparkles,
  Square,
  Star,
  StopCircle,
  Sword,
  Target,
  Trash2,
  Users,
  Wrench,
  X,
  Zap,
  ChevronUp,
  ChevronDown,
  CircleDollarSign,
} from "lucide-react";
import type { LucideIcon } from "lucide-react";

interface IconSpec {
  Icon: LucideIcon;
  bg: string;
  fg: string;
}

const SPECS: Record<string, IconSpec> = {
  MoveTo: { Icon: ArrowRight, bg: "#1f6fb2", fg: "#ffffff" },
  AttackMove: { Icon: Sword, bg: "#b42828", fg: "#ffffff" },
  AttackObject: { Icon: Crosshair, bg: "#b42828", fg: "#ffffff" },
  ForceAttackObject: { Icon: Crosshair, bg: "#8a1f1f", fg: "#ffffff" },
  ForceAttackGround: { Icon: Target, bg: "#8a1f1f", fg: "#ffffff" },
  GuardMode: { Icon: Shield, bg: "#5b6777", fg: "#ffffff" },
  StopMoving: { Icon: Square, bg: "#444444", fg: "#ffffff" },
  Scatter: { Icon: Sparkles, bg: "#7a4a8a", fg: "#ffffff" },
  SetRallyPoint: { Icon: Flag, bg: "#2e8b57", fg: "#ffffff" },
  Sell: { Icon: CircleDollarSign, bg: "#c4572d", fg: "#ffffff" },
  Enter: { Icon: LogIn, bg: "#0f6a8b", fg: "#ffffff" },
  ExitContainer: { Icon: LogOut, bg: "#0f6a8b", fg: "#ffffff" },
  Evacuate: { Icon: DoorOpen, bg: "#0f6a8b", fg: "#ffffff" },
  CombatDrop: { Icon: ChevronDown, bg: "#0f6a8b", fg: "#ffffff" },
  RepairVehicle: { Icon: Wrench, bg: "#a07020", fg: "#ffffff" },
  RepairStructure: { Icon: Wrench, bg: "#a07020", fg: "#ffffff" },
  ResumeBuild: { Icon: Play, bg: "#a07020", fg: "#ffffff" },
  GatherDumpSupplies: { Icon: Package, bg: "#8b6f2a", fg: "#ffffff" },
  HackInternet: { Icon: Zap, bg: "#3a7d3a", fg: "#ffffff" },
  Cheer: { Icon: Star, bg: "#c89f2a", fg: "#0b121a" },
  ToggleOvercharge: { Icon: Zap, bg: "#7a4a8a", fg: "#ffffff" },
  ToggleFormationMode: { Icon: Hash, bg: "#5b6777", fg: "#ffffff" },
  SelectWeapon: { Icon: Repeat, bg: "#444444", fg: "#ffffff" },
  SnipeVehicle: { Icon: Octagon, bg: "#b42828", fg: "#ffffff" },
  UseWeapon: { Icon: Sword, bg: "#b42828", fg: "#ffffff" },
  SelectClearMines: { Icon: Trash2, bg: "#a07020", fg: "#ffffff" },
  AddWaypoint: { Icon: MapPin, bg: "#1f6fb2", fg: "#ffffff" },
  DirectParticleCannon: { Icon: Sparkles, bg: "#7a4a8a", fg: "#ffffff" },
  CancelUnit: { Icon: X, bg: "#8a1f1f", fg: "#ffffff" },
  CancelUpgrade: { Icon: X, bg: "#8a1f1f", fg: "#ffffff" },
  CancelBuild: { Icon: X, bg: "#8a1f1f", fg: "#ffffff" },
  BeginUpgrade: { Icon: ChevronUp, bg: "#3a7d3a", fg: "#ffffff" },
  CreateUnit: { Icon: Users, bg: "#2e6da4", fg: "#ffffff" },
  BuildObject: { Icon: Hammer, bg: "#a07020", fg: "#ffffff" },
  PurchaseScience: { Icon: Crown, bg: "#c89f2a", fg: "#0b121a" },
  SpecialPower: { Icon: Sparkles, bg: "#7a4a8a", fg: "#ffffff" },
  SpecialPowerAtLocation: { Icon: Sparkles, bg: "#7a4a8a", fg: "#ffffff" },
  SpecialPowerAtObject: { Icon: Sparkles, bg: "#7a4a8a", fg: "#ffffff" },
};

// Group icons (CreateGroup0..9, SelectGroup0..9). Single-digit number badge.
export function getActionIcon(action: string | undefined): IconSpec | { number: string; bg: string; fg: string } | null {
  if (!action) return null;
  if (SPECS[action]) return SPECS[action];
  const cg = action.match(/^CreateGroup(\d)$/);
  if (cg) return { number: `+${cg[1]}`, bg: "#2e6da4", fg: "#ffffff" };
  const sg = action.match(/^SelectGroup(\d)$/);
  if (sg) return { number: sg[1], bg: "#5b8a3a", fg: "#ffffff" };
  return null;
}
