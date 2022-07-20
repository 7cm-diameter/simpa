library(tidyverse)
library(comprexr)

### Constatnts
FPS <- 30 # per sec
TIMEWINDOW <- 3 # sec

### Read and merge data
pupil_paths <- list.files("./data/area", pattern = "csv", full.names = T) %>% sort

merged_pupils <- pupil_paths %>%
  lapply(., function(path) {
    d <- path %>% read.csv
    add_metadata_to_df(d, path)
}) %>%
  do.call(rbind, .)

### data preprocessing
rasterized_with_cs_onset <- merged_pupils %>%
  split(., list(.$date, .$subject, .$condition), drop = T) %>%
  lapply(., function(d) {
    d$pupil.area <- d$pupil.area %>% scale
    d$index <- seq_len(nrow(d))
    d$cs_onset <- diff(c(0, d$cs))
    cs_on_idx <- d %>% filter(cs_onset == 1) %>% (function(d) d$index)
    length(cs_on_idx) %>%
      seq_len %>%
      lapply(., function(i) {
        idx <- cs_on_idx[i]
        pre <- idx - FPS * TIMEWINDOW
        post <- idx + FPS * TIMEWINDOW
        d %>%
          filter(pre <= index & index <= post) %>%
          mutate(t = index - idx, trial = i) %>%
          select(-pupil.x, -pupil.y, -index, -cs_onset)
      }) %>%
      do.call(rbind, .)
}) %>%
  do.call(rbind, .)

# save processed data
write.csv(rasterized_with_cs_onset,
          "./data/pltdata/pupil_raster.csv",
          row.names = F)
