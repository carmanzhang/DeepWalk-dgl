#!/bin/bash

DIR=/home/zhangli/mydisk-3t/repo/scholarly-bigdata/cached/graph-embedding
python3 deepwalk.py --net_file $DIR/original-pmc-hetero-as-homo-graph-2023-12-22-15-15.tsv --emb_file emb.txt --adam --mix --lr 0.2 --mix --num_threads 15 --batch_size 100 --negative 3 --walk_length 30 --print_interval 1000 --num_walks 5 --window_size 5 --dim 64 --map_file original-pmc-hetero-as-homo-graph-2023-12-22-15-15.tsv.idmap --emb_file $DIR/original-pmc-hetero-as-homo-graph-2023-12-22-15-15.tsv.emb
python3 deepwalk.py --net_file $DIR/enhanced-pmc-hetero-as-homo-graph-2023-12-22-15-15.tsv --emb_file emb.txt --adam --mix --lr 0.2 --mix --num_threads 15 --batch_size 100 --negative 3 --walk_length 30 --print_interval 1000 --num_walks 5 --window_size 5 --dim 64 --map_file enhanced-pmc-hetero-as-homo-graph-2023-12-22-15-15.tsv.idmap --emb_file $DIR/enhanced-pmc-hetero-as-homo-graph-2023-12-22-15-15.tsv.emb
