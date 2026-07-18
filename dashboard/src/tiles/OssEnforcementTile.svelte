<script>
  import { onMount, onDestroy } from 'svelte';
  import { subscribe, fmtTime } from '../events.js';

  // B4.7: OSS enforcement — budget_exceeded filtered to the OSS budget_kind variants; surfaces the
  // action_taken (abort/refuse/revoke), subject_id, and (for revocations) the reason.
  const OSS_KINDS = new Set(['oss_wall_clock', 'oss_usd', 'oss_requester_cooldown', 'requester_revoked']);
  let feed = $state([]); // {kind, action, subject, reason}
  let connected = $state(false);
  let unsubscribe;

  function apply(msg) {
    const p = msg.payload;
    if (!OSS_KINDS.has(p.budget_kind)) return; // ignore the B2.x per-role budget overruns
    feed = [
      ...feed,
      { kind: p.budget_kind, action: p.action_taken, subject: p.subject_id, reason: p.reason || '', received_at: msg.received_at },
    ].slice(-50);
  }

  onMount(() => {
    unsubscribe = subscribe(['budget_exceeded'], apply, () => (connected = true));
  });
  onDestroy(() => unsubscribe?.());
</script>

<section>
  <h2>OSS Enforcement</h2>
  <small>budget_exceeded (oss_*)</small>
  {#if feed.length === 0}
    <p>no OSS enforcement yet{connected ? '' : ' (connecting…)'}</p>
  {:else}
    <ul>
      {#each feed as e, i (i)}
        <li><span class="ts">{fmtTime(e.received_at)}</span> <span>[{e.action}]</span> {e.kind} · {e.subject}{e.reason ? ` — ${e.reason}` : ''}</li>
      {/each}
    </ul>
  {/if}
</section>
