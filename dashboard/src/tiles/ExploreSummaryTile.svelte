<script>
  import { onMount, onDestroy } from 'svelte';
  import { subscribe } from '../events.js';

  // B1.6: explore_pass_completed — file/manifest/test/CI counts.
  let passes = $state([]); // {explore_pass_id, repo_path, file_count, manifest_count, test_count, ci_count}
  let connected = $state(false);
  let unsubscribe;

  function apply(msg) {
    const p = msg.payload;
    passes = [
      ...passes.filter((x) => x.explore_pass_id !== p.summary_ref),
      {
        explore_pass_id: p.summary_ref,
        repo_path: p.repo_path,
        file_count: p.file_count,
        manifest_count: p.manifest_count,
        test_count: p.test_count,
        ci_count: p.ci_count,
      },
    ];
  }

  onMount(() => {
    unsubscribe = subscribe(['explore_pass_completed'], apply, () => (connected = true));
  });
  onDestroy(() => unsubscribe?.());
</script>

<section>
  <h2>Explore-pass summary</h2>
  <small>proj_explore_summary</small>
  {#if passes.length === 0}
    <p>no explore-pass summary yet{connected ? '' : ' (connecting…)'}</p>
  {:else}
    <ul>
      {#each passes as x (x.explore_pass_id)}
        <li>
          <small>{x.repo_path}</small> — {x.file_count} files, {x.manifest_count} manifests,
          {x.test_count} test, {x.ci_count} CI
        </li>
      {/each}
    </ul>
  {/if}
</section>
