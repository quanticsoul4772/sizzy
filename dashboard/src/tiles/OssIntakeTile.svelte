<script>
  import { onMount, onDestroy } from 'svelte';
  import { subscribe, fmtTime } from '../events.js';

  // B4.7: OSS intake — recorded intakes + their accept/reject decisions; rejection_reason surfaced.
  let feed = $state([]); // {event_type, label, detail}
  let connected = $state(false);
  let unsubscribe;

  function apply(msg) {
    const p = msg.payload;
    let label = '', detail = '';
    if (msg.event_type === 'oss_task_intake') {
      label = 'intake';
      detail = `${p.upstream_repo} ← ${p.requester_id}`;
    } else {
      label = p.decision; // accepted | rejected
      detail = p.decision === 'rejected' ? `${p.rejection_reason}` : `${p.intake_correlation_id}`;
    }
    feed = [...feed, { event_type: msg.event_type, label, detail, received_at: msg.received_at }].slice(-50);
  }

  onMount(() => {
    unsubscribe = subscribe(['oss_task_intake', 'intake_decision'], apply, () => (connected = true));
  });
  onDestroy(() => unsubscribe?.());
</script>

<section>
  <h2>OSS Intake</h2>
  <small>oss_task_intake · intake_decision</small>
  {#if feed.length === 0}
    <p>no OSS intake yet{connected ? '' : ' (connecting…)'}</p>
  {:else}
    <ul>
      {#each feed as e, i (i)}
        <li><span class="ts">{fmtTime(e.received_at)}</span> <span>[{e.label}]</span> {e.detail}</li>
      {/each}
    </ul>
  {/if}
</section>
