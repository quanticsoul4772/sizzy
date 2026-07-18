<script>
  import { onMount, onDestroy } from 'svelte';
  import { subscribe, fmtTime } from '../events.js';

  // B2.9: lock holder (from write_lock_acquired/released) + checkpoint/rewind feed.
  let holder = $state(null); // current lock holder role, or null
  let feed = $state([]); // checkpoint_taken / rewind_performed
  let connected = $state(false);
  let unsubscribe;

  function apply(msg) {
    const p = msg.payload;
    if (msg.event_type === 'write_lock_acquired') {
      holder = p.holder_role;
    } else if (msg.event_type === 'write_lock_released') {
      holder = null;
    } else if (msg.event_type === 'checkpoint_taken') {
      feed = [...feed, { kind: 'checkpoint', task_id: p.task_id, sha: p.git_commit_sha ?? p.ref, received_at: msg.received_at }].slice(-50);
    } else if (msg.event_type === 'rewind_performed') {
      feed = [...feed, { kind: 'rewind', task_id: p.task_id, sha: p.git_commit_sha, received_at: msg.received_at }].slice(-50);
    }
  }

  onMount(() => {
    unsubscribe = subscribe(
      ['write_lock_acquired', 'write_lock_released', 'checkpoint_taken', 'rewind_performed'],
      apply,
      () => (connected = true),
    );
  });
  onDestroy(() => unsubscribe?.());
</script>

<section>
  <h2>Lock &amp; checkpoints</h2>
  <small>proj_lock / proj_checkpoints</small>
  <p>lock holder: {holder ?? '(free)'}{connected ? '' : ' (connecting…)'}</p>
  {#if feed.length > 0}
    <ul>
      {#each feed as f, i (i)}
        <li><span class="ts">{fmtTime(f.received_at)}</span> <span>[{f.kind}]</span> {f.task_id} <small>{f.sha}</small></li>
      {/each}
    </ul>
  {/if}
</section>
