<script>
  import Tile from './Tile.svelte';
  import { TILES } from './tiles.js';
  import { SIDECAR_ADDR } from './sidecar.js';
  // B1.6: 6 dedicated read-only-loop tiles (the 12 above are generic projection tiles).
  import QuestionsTile from './tiles/QuestionsTile.svelte';
  import AssumptionsTile from './tiles/AssumptionsTile.svelte';
  import DraftSpecTile from './tiles/DraftSpecTile.svelte';
  import SignedSpecTile from './tiles/SignedSpecTile.svelte';
  import PlanTile from './tiles/PlanTile.svelte';
  import ExploreSummaryTile from './tiles/ExploreSummaryTile.svelte';
  // B2.9: 5 dedicated write-phase tiles.
  import DeveloperActivityTile from './tiles/DeveloperActivityTile.svelte';
  import VerifierOutcomesTile from './tiles/VerifierOutcomesTile.svelte';
  import ReviewerCertsTile from './tiles/ReviewerCertsTile.svelte';
  import LockCheckpointTile from './tiles/LockCheckpointTile.svelte';
  import TrustStateTile from './tiles/TrustStateTile.svelte';
  // B3.8: 2 dedicated maintenance/adversarial tiles.
  import MaintenanceTile from './tiles/MaintenanceTile.svelte';
  import AdversarialTile from './tiles/AdversarialTile.svelte';
  // B4.7: 3 OSS-envelope visibility tiles.
  import OssIntakeTile from './tiles/OssIntakeTile.svelte';
  import OssEnforcementTile from './tiles/OssEnforcementTile.svelte';
  import OssBranchTile from './tiles/OssBranchTile.svelte';
  // B5.6: 4 dedicated learning-spine visibility tiles.
  import CandidateQueueTile from './tiles/CandidateQueueTile.svelte';
  import AntibodyLibraryTile from './tiles/AntibodyLibraryTile.svelte';
  import RetroActivityTile from './tiles/RetroActivityTile.svelte';
  import TrustedMemoryTile from './tiles/TrustedMemoryTile.svelte';
  // OS-resource accounting tile.
  import ResourceHealthTile from './tiles/ResourceHealthTile.svelte';
  // per-role LLM spend (rev 0.3.81).
  import CostTile from './tiles/CostTile.svelte';
  import InvariantMonitorTile from './tiles/InvariantMonitorTile.svelte';
</script>

<header>
  <h1>devharness dashboard</h1>
  <p>sidecar: {SIDECAR_ADDR}</p>
</header>

<main>
  {#each TILES as tile (tile.table)}
    <Tile title={tile.title} table={tile.table} eventTypes={tile.eventTypes} />
  {/each}
  <QuestionsTile />
  <AssumptionsTile />
  <DraftSpecTile />
  <SignedSpecTile />
  <PlanTile />
  <ExploreSummaryTile />
  <DeveloperActivityTile />
  <VerifierOutcomesTile />
  <ReviewerCertsTile />
  <LockCheckpointTile />
  <TrustStateTile />
  <MaintenanceTile />
  <AdversarialTile />
  <OssIntakeTile />
  <OssEnforcementTile />
  <OssBranchTile />
  <CandidateQueueTile />
  <AntibodyLibraryTile />
  <RetroActivityTile />
  <TrustedMemoryTile />
  <ResourceHealthTile />
  <CostTile />
  <InvariantMonitorTile />
</main>
