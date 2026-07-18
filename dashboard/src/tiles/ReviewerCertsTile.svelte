<script>
  import { onMount, onDestroy } from 'svelte';
  import { subscribe } from '../events.js';

  // B2.9: reviewer certifications — reviewer_certified / reviewer_rejected.
  let certs = $state([]); // {task_id, verdict, reason}
  let connected = $state(false);
  let unsubscribe;

  function apply(msg) {
    const p = msg.payload;
    if (msg.event_type === 'reviewer_certified') {
      certs = [...certs, { task_id: p.task_id, verdict: 'certified', reason: '' }].slice(-50);
    } else if (msg.event_type === 'reviewer_rejected') {
      certs = [...certs, { task_id: p.task_id, verdict: 'rejected', reason: p.reason }].slice(-50);
    }
  }

  onMount(() => {
    unsubscribe = subscribe(['reviewer_certified', 'reviewer_rejected'], apply, () => (connected = true));
  });
  onDestroy(() => unsubscribe?.());
</script>

<section>
  <h2>Reviewer certifications</h2>
  <small>proj_reviewer_certs</small>
  {#if certs.length === 0}
    <p>no reviewer certifications yet{connected ? '' : ' (connecting…)'}</p>
  {:else}
    <ul>
      {#each certs as c, i (i)}
        <li>
          <span>[{c.verdict}]</span> {c.task_id}{c.verdict === 'rejected' ? ` — ${c.reason}` : ''}
        </li>
      {/each}
    </ul>
  {/if}
</section>
